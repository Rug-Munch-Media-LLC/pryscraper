"""A 429 must never be retried in 50 ms.

Regression for ``pry_sdk._send`` — the old ladder slept
``min(0.05 * 2**attempt, 2.0)``, so a server asking for 60 s got a retry after
50 ms and the fleet earned a ban.
"""

from __future__ import annotations

import asyncio

import httpx

from pry.api import pry_sdk


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def request(self, *args: object, **kwargs: object) -> httpx.Response:
        response = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return response


def _send(monkeypatch, responses: list[httpx.Response]):
    slept: list[float] = []

    async def fake_sleep(delay: float, *args: object, **kwargs: object) -> None:
        slept.append(delay)

    client = _FakeClient(responses)
    monkeypatch.setattr(pry_sdk.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(pry_sdk.asyncio, "sleep", fake_sleep)
    response = asyncio.run(pry_sdk.PryCrawl(base_url="http://test", max_retries=2)._send("GET", "/x"))
    return response, slept


def test_retry_after_is_honoured(monkeypatch):
    response, slept = _send(
        monkeypatch,
        [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200)],
    )
    assert response.status_code == 200
    assert slept, "429 was not retried at all"
    assert slept[0] >= 2.0, f"429 retried after {slept[0]:.3g}s; Retry-After: 2 ignored"


def test_success_never_sleeps(monkeypatch):
    response, slept = _send(monkeypatch, [httpx.Response(200)])
    assert response.status_code == 200
    assert slept == []
