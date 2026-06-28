from dataclasses import dataclass, field

import httpx

from internal.metrics.window import Snapshot


@dataclass
class Metrics:
    canary_percent: int = 0
    stable: Snapshot = field(default_factory=Snapshot)
    canary: Snapshot = field(default_factory=Snapshot)

    @classmethod
    def from_dict(cls, data: dict) -> "Metrics":
        stable_data = data.get("stable", {})
        canary_data = data.get("canary", {})
        return cls(
            canary_percent=int(data.get("canaryPercent", 0)),
            stable=Snapshot(
                requests=int(stable_data.get("requests", 0)),
                errors=int(stable_data.get("errors", 0)),
                error_rate=float(stable_data.get("errorRate", 0.0)),
                p99_latency_ms=int(stable_data.get("p99LatencyMs", 0)),
            ),
            canary=Snapshot(
                requests=int(canary_data.get("requests", 0)),
                errors=int(canary_data.get("errors", 0)),
                error_rate=float(canary_data.get("errorRate", 0.0)),
                p99_latency_ms=int(canary_data.get("p99LatencyMs", 0)),
            ),
        )


class Client:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._http = httpx.Client(timeout=3.0)

    def Metrics(self) -> tuple[Metrics, Exception | None]:
        try:
            res = self._http.get(f"{self._base_url}/metrics")
            if res.status_code < 200 or res.status_code > 299:
                return Metrics(), Exception(f"router returned {res.status_code} {res.reason_phrase}")
            return Metrics.from_dict(res.json()), None
        except Exception as exc:
            return Metrics(), exc

    def Rollout(self, percent: int) -> Exception | None:
        return self._post("/rollout", {"canaryPercent": percent})

    def Rollback(self) -> Exception | None:
        return self._post("/rollback", None)

    def _post(self, path: str, body: dict | None) -> Exception | None:
        try:
            headers = {"Content-Type": "application/json"} if body is not None else None
            res = self._http.post(f"{self._base_url}{path}", json=body, headers=headers)
            if res.status_code < 200 or res.status_code > 299:
                return Exception(f"router returned {res.status_code} {res.reason_phrase}")
            return None
        except Exception as exc:
            return exc


def new_client(base_url: str) -> Client:
    return Client(base_url)
