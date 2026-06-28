import sys
import threading

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from internal.env import String, Int
from internal.flags.client import FraudModel, Response


def clamp_percent(value: int) -> int:
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


class FlagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    rolloutPercent: int


class Store:
    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._fraud_model = FraudModel(
            enabled=Int("FRAUD_MODEL_ENABLED", 0) == 1,
            rollout_percent=clamp_percent(Int("FRAUD_MODEL_ROLLOUT_PERCENT", 0)),
        )

    def snapshot(self) -> dict:
        with self._mu:
            return Response(fraud_model=self._fraud_model).to_dict()

    def update_fraud_model(self, input_data: FlagUpdate) -> dict:
        with self._mu:
            self._fraud_model = FraudModel(
                enabled=input_data.enabled,
                rollout_percent=clamp_percent(input_data.rolloutPercent),
            )
            current = self._fraud_model
        return Response(fraud_model=current).to_dict()

    def kill_fraud_model(self) -> dict:
        with self._mu:
            self._fraud_model = FraudModel()
        return self.snapshot()


store = Store()
app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/flags")
def get_flags() -> dict:
    return store.snapshot()


@app.post("/flags/fraud-model")
def update_fraud_model(body: FlagUpdate) -> dict:
    return store.update_fraud_model(body)


@app.post("/flags/fraud-model/kill")
def kill_fraud_model() -> dict:
    return store.kill_fraud_model()


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
