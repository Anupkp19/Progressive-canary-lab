import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class Counters:
    def __init__(self) -> None:
        self._mu = threading.Lock()
        self.total = 0
        self.ok = 0
        self.failed = 0
        self.canary = 0

    def inc_total(self) -> None:
        with self._mu:
            self.total += 1

    def inc_ok(self) -> None:
        with self._mu:
            self.ok += 1

    def inc_failed(self) -> None:
        with self._mu:
            self.failed += 1

    def inc_canary(self) -> None:
        with self._mu:
            self.canary += 1

    def snapshot(self) -> tuple[int, int, int, int]:
        with self._mu:
            return self.total, self.ok, self.failed, self.canary


def send(client: httpx.Client, target: str, mode: str, user_id: int, counts: Counters) -> None:
    url = f"{target.rstrip('/')}/checkout"
    headers = {"X-User-ID": f"{mode}-user-{user_id}"}
    try:
        res = client.get(url, headers=headers)
    except httpx.HTTPError:
        counts.inc_failed()
        return

    counts.inc_total()
    try:
        if res.headers.get("X-Progressive-Delivery-Target") == "canary":
            counts.inc_canary()
        if 200 <= res.status_code <= 499:
            counts.inc_ok()
            return
        counts.inc_failed()
    finally:
        res.close()


def parse_duration(value: str) -> float:
    if value.endswith("s"):
        return float(value[:-1])
    if value.endswith("m"):
        return float(value[:-1]) * 60
    if value.endswith("h"):
        return float(value[:-1]) * 3600
    return float(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://router:8080", help="router base URL")
    parser.add_argument("--duration", default="90s", help="run duration (e.g. 90s)")
    parser.add_argument("--rps", type=int, default=20, help="requests per second")
    parser.add_argument("--mode", default="normal", choices=["normal", "bad"], help="normal or bad")
    args = parser.parse_args()

    duration_sec = parse_duration(args.duration)
    rps = max(1, args.rps)
    interval = 1.0 / rps

    log.info(
        "loadgen started mode=%s target=%s duration=%ss rps=%d",
        args.mode,
        args.target,
        duration_sec,
        rps,
    )

    client = httpx.Client(timeout=5.0)
    counts = Counters()
    deadline = time.monotonic() + duration_sec
    user_index = 0
    user_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=rps * 2) as executor:
        while time.monotonic() < deadline:
            tick_start = time.monotonic()
            with user_lock:
                user_index += 1
                current_user = user_index
            executor.submit(send, client, args.target, args.mode, current_user, counts)
            elapsed = time.monotonic() - tick_start
            sleep_for = interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

        executor.shutdown(wait=True)

    total, ok, failed, canary = counts.snapshot()
    log.info("loadgen complete total=%d ok=%d failed=%d canary=%d", total, ok, failed, canary)
    client.close()


if __name__ == "__main__":
    main()
