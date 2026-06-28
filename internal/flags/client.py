from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class FraudModel:
    enabled: bool = False
    rollout_percent: int = 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "rolloutPercent": self.rollout_percent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FraudModel":
        return cls(
            enabled=bool(data.get("enabled", False)),
            rollout_percent=int(data.get("rolloutPercent", 0)),
        )


@dataclass
class Response:
    fraud_model: FraudModel = field(default_factory=FraudModel)

    def to_dict(self) -> dict:
        return {"fraudModel": self.fraud_model.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "Response":
        return cls(fraud_model=FraudModel.from_dict(data.get("fraudModel", {})))


class Client:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._http = httpx.Client(timeout=2.0)

    def Flags(self) -> tuple[Response, Optional[Exception]]:
        flags = Response()
        if self._base_url == "":
            return flags, None

        try:
            res = self._http.get(f"{self._base_url}/flags")
            if res.status_code < 200 or res.status_code > 299:
                return flags, Exception(f"flag service returned {res.status_code} {res.reason_phrase}")
            data = res.json()
            return Response.from_dict(data), None
        except Exception as exc:
            return flags, exc


def new_client(base_url: str) -> Client:
    return Client(base_url)


def _fnv1a_32(data: bytes) -> int:
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def EnabledFor(flag: FraudModel, key: str) -> bool:
    if not flag.enabled or flag.rollout_percent <= 0:
        return False
    if flag.rollout_percent >= 100:
        return True
    digest = _fnv1a_32(key.encode("utf-8"))
    return int(digest % 100) < flag.rollout_percent
