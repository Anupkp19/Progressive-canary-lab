import logging
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from internal.env import String, Int
from internal.flags.admin import AdminClient
from internal.flags.client import FraudModel
from internal.routerclient.client import Client, Metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

STAGES = [1, 5, 25, 50, 100]


class Controller:
    def __init__(self) -> None:
        self.router = Client(String("ROUTER_URL", "http://router:8080"))
        self.flags = AdminClient(String("FEATURE_FLAG_URL", "http://flag-service:8080"))
        self.interval = Int("CHECK_INTERVAL_SECONDS", 10)
        self.min_canary_req = Int("MIN_CANARY_REQUESTS", 5)

    def check(self) -> None:
        data, err = self.router.Metrics()
        if err is not None:
            log.info('health_check status=error reason="%s"', err)
            return

        if data.canary_percent == 0:
            log.info("health_check canary_percent=0 state=rolled_back")
            return

        if data.canary.requests < self.min_canary_req:
            log.info(
                "health_check canary_percent=%d canary_requests=%d state=waiting_for_samples",
                data.canary_percent,
                data.canary.requests,
            )
            return

        if unhealthy(data):
            log.info(
                "rollback triggered canary_percent=%d error_rate=%.4f p99_ms=%d",
                data.canary_percent,
                data.canary.error_rate,
                data.canary.p99_latency_ms,
            )
            if err := self.router.Rollback():
                log.info('rollback router_status=error reason="%s"', err)
            if err := self.flags.KillFraudModel():
                log.info('rollback kill_switch_status=error reason="%s"', err)
            log.info("rollback complete canary_percent=0 fraud_model=disabled")
            return

        next_stage, ok = next_stage_for(data.canary_percent)
        if not ok:
            log.info(
                "health_check canary_percent=%d state=complete error_rate=%.4f p99_ms=%d",
                data.canary_percent,
                data.canary.error_rate,
                data.canary.p99_latency_ms,
            )
            return

        if err := self.router.Rollout(next_stage):
            log.info(
                'promotion status=error from=%d to=%d reason="%s"',
                data.canary_percent,
                next_stage,
                err,
            )
            return
        if err := self.flags.SetFraudModel(
            FraudModel(enabled=True, rollout_percent=next_stage)
        ):
            log.info('promotion flag_status=error rollout_percent=%d reason="%s"', next_stage, err)
            return
        log.info(
            "promotion complete from=%d to=%d error_rate=%.4f p99_ms=%d",
            data.canary_percent,
            next_stage,
            data.canary.error_rate,
            data.canary.p99_latency_ms,
        )


def unhealthy(data: Metrics) -> bool:
    return data.canary.error_rate >= 0.02 or data.canary.p99_latency_ms >= 500


def next_stage_for(current: int) -> tuple[int, bool]:
    for stage in STAGES:
        if stage > current:
            return stage, True
    return current, False


def main() -> None:
    controller = Controller()
    log.info("controller started stages=%s error_threshold=0.02 p99_threshold_ms=500", STAGES)
    while True:
        controller.check()
        time.sleep(controller.interval)


if __name__ == "__main__":
    main()
