import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List


@dataclass
class Snapshot:
    requests: int = 0
    errors: int = 0
    error_rate: float = field(default=0.0, metadata={"json": "errorRate"})
    p99_latency_ms: int = field(default=0, metadata={"json": "p99LatencyMs"})

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "errors": self.errors,
            "errorRate": self.error_rate,
            "p99LatencyMs": self.p99_latency_ms,
        }


class Window:
    def __init__(self, limit: int) -> None:
        if limit <= 0:
            limit = 1000
        self._mu = threading.Lock()
        self._limit = limit
        self._requests = 0
        self._errors = 0
        self._latencies: List[timedelta] = []

    def Record(self, latency: timedelta, failed: bool) -> None:
        with self._mu:
            self._requests += 1
            if failed:
                self._errors += 1

            self._latencies.append(latency)
            if len(self._latencies) > self._limit:
                self._latencies = self._latencies[-self._limit :]

    def Snapshot(self) -> Snapshot:
        with self._mu:
            snapshot = Snapshot(requests=self._requests, errors=self._errors)
            if self._requests > 0:
                snapshot.error_rate = self._errors / self._requests
            if self._latencies:
                values = sorted(self._latencies)
                index = int(len(values) * 0.99) - 1
                if index < 0:
                    index = 0
                if index >= len(values):
                    index = len(values) - 1
                snapshot.p99_latency_ms = int(values[index].total_seconds() * 1000)
            return snapshot


def new_window(limit: int) -> Window:
    return Window(limit)
