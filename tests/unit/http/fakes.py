from __future__ import annotations

from collections.abc import Iterable

from djua_sms_gateway.http.client import HttpResult


class FakeHttpClient:
    def __init__(self, outcomes: Iterable[HttpResult | Exception] = ()) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def post_json(self, url: str, body: str, headers: dict[str, str]) -> HttpResult:
        self.calls.append((url, body, dict(headers)))
        outcome = self.outcomes.pop(0) if self.outcomes else HttpResult(200)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
