import math
import random
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from internal.env import String, Int, Float
from internal.flags.client import Client, EnabledFor, Response
from internal.metrics.window import Window



def normalize_rate(value: float) -> float:
    if math.isnan(value) or value < 0:
        return 0.0
    if value > 1:
        return value / 100
    return value


def jitter(max_delta: timedelta) -> timedelta:
    if max_delta <= timedelta(0):
        return timedelta(0)
    return timedelta(microseconds=random.randrange(int(max_delta.total_seconds() * 1_000_000)))


def request_key(request: Request) -> str:
    value = request.headers.get("X-User-ID", "")
    if value:
        return value
    value = request.query_params.get("user", "")
    if value:
        return value
    return secrets.token_hex(8)


def deployment_stage(version: str) -> str:
    if version == "v2":
        return "canary"
    return "stable"


def fraud_decision(enabled: bool) -> str:
    if enabled:
        return "new-model-score"
    return "legacy-rules"


def parse_addr(addr: str) -> tuple[str, int]:
    if addr.startswith(":"):
        return "0.0.0.0", int(addr[1:])
    if addr.count(":") == 1:
        host, port = addr.split(":", 1)
        return host, int(port)
    return "0.0.0.0", int(addr)



class FlagCache:
    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self._response = Response()

    def get_if_valid(self, now: datetime) -> Response | None:
        with self._mu:
            if now < self._expires_at:
                return self._response
        return None

    def set(self, response: Response, expires_at: datetime) -> None:
        with self._mu:
            self._response = response
            self._expires_at = expires_at


class Server:
    def __init__(self) -> None:
        self.version = String("VERSION", "v1")
        self.error_rate = normalize_rate(Float("ERROR_RATE", 0))
        self.base_latency = timedelta(milliseconds=Int("BASE_LATENCY_MS", 120))
        self.metrics = Window(2000)
        self.flag_client = Client(String("FEATURE_FLAG_URL", ""))
        self.started_at = datetime.now(timezone.utc)
        self.extra_latency = timedelta(milliseconds=Int("FRAUD_MODEL_LATENCY_MS", 80))
        self.fraud_error_pct = normalize_rate(Float("FRAUD_MODEL_ERROR_RATE", 0))
        self.flag_cache = FlagCache()

    def model_enabled(self, user_id: str) -> bool:
        if self.version != "v2":
            return False
        response, err = self.flags()
        if err is not None:
            return False
        return EnabledFor(response.fraud_model, user_id)

    def flags(self) -> tuple[Response, Exception | None]:
        now = datetime.now(timezone.utc)
        cached = self.flag_cache.get_if_valid(now)
        if cached is not None:
            return cached, None

        response, err = self.flag_client.Flags()
        if err is not None:
            return response, err

        self.flag_cache.set(response, now + timedelta(milliseconds=500))
        return response, None




server = Server()
app = FastAPI()


@app.get("/health")
def health() -> dict:
    uptime = int((datetime.now(timezone.utc) - server.started_at).total_seconds())
    return {"ok": True, "version": server.version, "uptimeSec": uptime}


@app.get("/checkout")
def checkout(request: Request):
    start = time.monotonic()
    user_id = request_key(request)
    model = server.model_enabled(user_id)
    latency = server.base_latency + jitter(timedelta(milliseconds=35))
    failed = random.random() < server.error_rate

    if model:
        latency += server.extra_latency + jitter(timedelta(milliseconds=50))
        if random.random() < server.fraud_error_pct:
            failed = True

    time.sleep(latency.total_seconds())
    elapsed = timedelta(seconds=time.monotonic() - start)
    server.metrics.Record(elapsed, failed)

    payload = {
        "version": server.version,
        "fraudModelUsed": model,
        "latencyMs": int(elapsed.total_seconds() * 1000),
        "deploymentStage": deployment_stage(server.version),
    }
    if failed:
        return JSONResponse(status_code=500, content={**payload, "ok": False, "message": "checkout failed"})
    return {**payload, "ok": True, "message": "checkout approved"}


@app.get("/fraud-check")
def fraud_check(request: Request) -> dict:
    user_id = request_key(request)
    enabled = server.model_enabled(user_id)
    return {
        "version": server.version,
        "fraudModelUsed": enabled,
        "decision": fraud_decision(enabled),
    }


@app.get("/metrics")
def service_metrics() -> dict:
    return {
        "version": server.version,
        "metrics": server.metrics.Snapshot().to_dict(),
    }


def main() -> None:
    host, port = parse_addr(String("ADDR", ":8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
