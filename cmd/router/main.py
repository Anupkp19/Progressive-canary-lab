import logging
import random
import secrets
import sys
import threading
import time
from datetime import timedelta
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from internal.env import String, Int
from internal.metrics.window import Window

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class Target(str, Enum):
    STABLE = "stable"
    CANARY = "canary"


class RolloutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canaryPercent: int


def clamp_percent(value: int) -> int:
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


def must_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"invalid URL: {value}")
    return value.rstrip("/")


def copy_headers(dst: httpx.Headers, src: httpx.Headers) -> None:
    for key, value in src.items():
        dst[key] = value


def single_joining_slash(a: str, b: str) -> str:
    aslash = a.endswith("/")
    bslash = b.startswith("/")
    if aslash and bslash:
        return a + b[1:]
    if not aslash and not bslash:
        return a + "/" + b
    return a + b


class Router:
    def __init__(self) -> None:
        self._stable_url = must_url(String("STABLE_URL", "http://app-stable:8080"))
        self._canary_url = must_url(String("CANARY_URL", "http://app-canary:8080"))
        self._client = httpx.Client(timeout=5.0)
        self._mu = threading.RLock()
        self._canary_percent = clamp_percent(Int("CANARY_PERCENT", 1))
        self._stable_metrics = Window(4000)
        self._canary_metrics = Window(4000)

    def percent(self) -> int:
        with self._mu:
            return self._canary_percent

    def set_percent(self, percent: int) -> None:
        clamped = clamp_percent(percent)
        with self._mu:
            self._canary_percent = clamped
        log.info("rollout canary_percent=%d", clamped)

    def snapshot(self) -> dict[str, Any]:
        return {
            "canaryPercent": self.percent(),
            "stable": self._stable_metrics.Snapshot().to_dict(),
            "canary": self._canary_metrics.Snapshot().to_dict(),
        }

    def choose(self) -> Target:
        percent = self.percent()
        if percent <= 0:
            return Target.STABLE
        if percent >= 100:
            return Target.CANARY
        if random.randrange(100) < percent:
            return Target.CANARY
        return Target.STABLE

    def target_url(self, chosen: Target, path: str, query: str) -> str:
        base = self._canary_url if chosen == Target.CANARY else self._stable_url
        joined = single_joining_slash(urlparse(base).path or "", path)
        url = f"{base.split('://', 1)[0]}://{urlparse(base).netloc}{joined}"
        if query:
            url = f"{url}?{query}"
        return url

    def record(self, chosen: Target, latency: timedelta, failed: bool) -> None:
        if chosen == Target.CANARY:
            self._canary_metrics.Record(latency, failed)
        else:
            self._stable_metrics.Record(latency, failed)

    async def proxy(self, request: Request) -> Response:
        if request.url.path not in ("/checkout", "/fraud-check"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        chosen = self.choose()
        target_url = self.target_url(chosen, request.url.path, request.url.query)
        body = await request.body()

        headers = dict(request.headers)
        if not headers.get("x-user-id") and not headers.get("X-User-ID"):
            headers["X-User-ID"] = f"local-user-{secrets.randbits(63)}"

        start = time.monotonic()
        try:
            res = self._client.request(
                request.method,
                target_url,
                headers=headers,
                content=body,
            )
        except httpx.HTTPError as exc:
            latency = timedelta(seconds=time.monotonic() - start)
            self.record(chosen, latency, True)
            log.info(
                "target=%s status=502 latency_ms=%d canary_percent=%d path=%s",
                chosen.value,
                int(latency.total_seconds() * 1000),
                self.percent(),
                request.url.path,
            )
            return JSONResponse(
                status_code=502,
                content={"error": str(exc), "target": chosen.value},
            )

        latency = timedelta(seconds=time.monotonic() - start)
        failed = res.status_code >= 500
        self.record(chosen, latency, failed)
        log.info(
            "target=%s status=%d latency_ms=%d canary_percent=%d path=%s",
            chosen.value,
            res.status_code,
            int(latency.total_seconds() * 1000),
            self.percent(),
            request.url.path,
        )

        response_headers = dict(res.headers)
        response_headers["X-Progressive-Delivery-Target"] = chosen.value
        return Response(
            content=res.content,
            status_code=res.status_code,
            headers=response_headers,
        )


router = Router()
app = FastAPI()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "canaryPercent": router.percent()}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    return router.snapshot()


@app.post("/rollout")
async def rollout(body: RolloutRequest) -> dict[str, Any]:
    router.set_percent(body.canaryPercent)
    return router.snapshot()


@app.post("/rollback")
def rollback() -> dict[str, Any]:
    router.set_percent(0)
    return router.snapshot()


@app.api_route("/checkout", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@app.api_route("/fraud-check", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_routes(request: Request) -> Response:
    return await router.proxy(request)


def parse_addr(addr: str) -> tuple[str, int]:
    if addr.startswith(":"):
        return "0.0.0.0", int(addr[1:])
    if addr.count(":") == 1:
        host, port = addr.split(":", 1)
        return host, int(port)
    return "0.0.0.0", int(addr)


def main() -> None:
    host, port = parse_addr(String("ADDR", ":8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
