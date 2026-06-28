import httpx

from internal.flags.client import FraudModel


class AdminClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._http = httpx.Client(timeout=3.0)

    def SetFraudModel(self, flag: FraudModel) -> Exception | None:
        return self._post("/flags/fraud-model", flag.to_dict())

    def KillFraudModel(self) -> Exception | None:
        return self._post("/flags/fraud-model/kill", None)

    def _post(self, path: str, body: dict | None) -> Exception | None:
        try:
            headers = {"Content-Type": "application/json"} if body is not None else None
            res = self._http.post(f"{self._base_url}{path}", json=body, headers=headers)
            if res.status_code < 200 or res.status_code > 299:
                return Exception(f"flag service returned {res.status_code} {res.reason_phrase}")
            return None
        except Exception as exc:
            return exc


def new_admin_client(base_url: str) -> AdminClient:
    return AdminClient(base_url)
