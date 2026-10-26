"""T0 profile: what goes on the wire, and when we are allowed to say solved."""

from __future__ import annotations

import pytest
from curl_cffi.requests import Cookies

from pry.engine.captcha import t0_profile as t0

URL_A = "https://a.example/one"
URL_A2 = "https://a.example/two"
URL_B = "https://b.example/one"
OK = "<html><body>hello</body></html>"


class _Transport:
    """Stand-in for the network: replays replies, records what was sent."""

    def __init__(self, replies: list[tuple[int, str, tuple[str, str] | None]]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, timeout_s: float, cookies: Cookies) -> t0.Reply:
        self.calls.append((url, cookies.get_dict()))
        status, text, cookie = self._replies.pop(0)
        handed_back = Cookies(dict(cookies.get_dict()))
        if cookie is not None:
            handed_back.set(cookie[0], cookie[1], domain=t0.domain_of(url))
        return t0.Reply(status=status, text=text, cookies=handed_back)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    t0.jars.clear()
    monkeypatch.setattr(t0, "capability", lambda: True)


def test_profile_is_a_chrome_alias() -> None:
    assert t0.PROFILE == "chrome"


def test_no_static_user_agent_is_hardcoded() -> None:
    static = {name.lower() for name in t0.base_headers()}
    assert "user-agent" not in static
    assert "sec-ch-ua" not in static


@pytest.mark.parametrize(
    ("status", "html", "reason"),
    [
        (200, OK, "solved"),
        (200, "<html>Just a moment...</html>", "unsolved.marker"),
        (200, "   ", "unsolved.empty"),
        (403, "<html>denied</html>", "unsolved.http_403"),
        (503, "<html></html>", "unsolved.http_503"),
        (302, "<html>moved</html>", "unsolved.http_302"),
    ],
)
def test_classify_only_a_clean_200_is_solved(status: int, html: str, reason: str) -> None:
    assert t0.classify(status, html) == reason


@pytest.mark.asyncio
async def test_cookie_jar_survives_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport([(200, OK, ("sid", "abc")), (200, OK, None)])
    monkeypatch.setattr(t0, "_http_get", transport)

    assert await t0.fetch_clean(URL_A) == (OK, "solved")
    assert await t0.fetch_clean(URL_A2) == (OK, "solved")
    assert transport.calls[0] == (URL_A, {})
    assert transport.calls[1] == (URL_A2, {"sid": "abc"})


@pytest.mark.asyncio
async def test_cookie_jar_is_per_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport([(200, OK, ("sid", "abc")), (200, OK, None)])
    monkeypatch.setattr(t0, "_http_get", transport)

    await t0.fetch_clean(URL_A)
    await t0.fetch_clean(URL_B)
    assert transport.calls[1] == (URL_B, {})


@pytest.mark.asyncio
async def test_blocked_status_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport([(403, "denied", None)])
    monkeypatch.setattr(t0, "_http_get", transport)

    assert await t0.fetch_clean(URL_A) == (None, "unsolved.http_403")
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_transport_error_is_a_typed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _boom(url: str, timeout_s: float, cookies: Cookies) -> t0.Reply:
        calls.append(url)
        raise OSError("connection reset")

    monkeypatch.setattr(t0, "_http_get", _boom)
    assert await t0.fetch_clean(URL_A) == (None, "failed")
    assert calls == [URL_A]


@pytest.mark.asyncio
async def test_disabled_path_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _boom(url: str, timeout_s: float, cookies: Cookies) -> t0.Reply:
        calls.append(url)
        raise AssertionError("must not be called")

    monkeypatch.setattr(t0, "capability", lambda: False)
    monkeypatch.setattr(t0, "_http_get", _boom)
    assert await t0.fetch_clean(URL_A) == (None, "unavailable.model")
    assert calls == []
