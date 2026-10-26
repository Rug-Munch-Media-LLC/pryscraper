"""Clearance cache: TTL, UA binding, invalidation, backends, inert when off (no network)."""

from __future__ import annotations

import json

import pytest

from pry.engine.captcha import clearance, lanes
from pry.engine.captcha.flaresolverr import FlareSolution
from pry.engine.captcha.lanes import Challenge

CF = "cf_clearance-value"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
OTHER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
CHALLENGE = Challenge(url="https://a.example/page", captcha_type="cloudflare")


class FakeRedis:
    """Minimal async stand-in for redis.asyncio.Redis (no connection)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.data.pop(key, None)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_CAPTCHA_CLEARANCE_ENABLED", "1")
    monkeypatch.setenv("PRY_CAPTCHA_CLEARANCE_BACKEND", "memory")
    monkeypatch.setattr(lanes.settings, "captcha_enabled", True)
    clearance.store.cache_clear()


def _store(**kwargs: object) -> clearance.ClearanceStore:
    return clearance.ClearanceStore(**kwargs)  # type: ignore[arg-type]


async def _put(store: clearance.ClearanceStore, domain: str = "a.example") -> None:
    assert await store.put(domain, {"cf_clearance": CF, "__cf_bm": "bm"}, UA, "T1") is not None


async def test_ttl_expiry_drops_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(clearance.time, "time", lambda: clock["t"])
    store = _store(ttl_s=10.0)
    await _put(store)
    assert await store.get("a.example") is not None

    clock["t"] = 1009.0
    assert await store.get("a.example") is not None

    clock["t"] = 1011.0
    assert await store.get("a.example") is None
    assert store._memory == {}


async def test_ua_mismatch_is_rejected() -> None:
    store = _store()
    await _put(store)
    assert await store.get("a.example", user_agent=UA) is not None
    assert await store.get("a.example", user_agent=OTHER_UA) is None
    # Unbound read (no UA supplied) still returns the pair for inspection.
    assert await store.get("a.example") is not None
    assert await store.put("a.example", {"cf_clearance": CF}, "", "T1") is None
    assert await store.put("a.example", {"__cf_bm": "bm"}, UA, "T1") is None


async def test_invalidation_is_per_domain_and_never_shared() -> None:
    store = _store()
    await _put(store, "a.example")
    await _put(store, "b.example")
    await store.invalidate("a.example")
    assert await store.get("a.example") is None  # invalidated
    assert await store.get("b.example") is not None  # same cookie, own entry
    assert await store.get("c.example") is None


async def test_redis_backend_is_selected_and_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_CAPTCHA_CLEARANCE_BACKEND", "redis")
    clearance.store.cache_clear()
    assert clearance.store().backend == "redis"
    fake = FakeRedis()
    await _put(_store(backend="redis", ttl_s=30.0, client=fake))
    assert fake.setex_calls
    assert fake.setex_calls[0][0] == "pry:clearance:a.example"
    assert fake.setex_calls[0][1] == 30

    seeded = _store(backend="redis", client=fake)
    assert await seeded.get("a.example", user_agent=UA) is not None
    assert await seeded.get("a.example", user_agent=OTHER_UA) is None
    await seeded.invalidate("a.example")
    assert fake.deleted == ["pry:clearance:a.example"]


async def test_redis_failure_degrades_to_memory() -> None:
    class Dead(FakeRedis):
        async def get(self, key: str) -> str | None:
            raise OSError("redis down")

        async def setex(self, key: str, ttl: int, value: str) -> None:
            raise OSError("redis down")

    store = _store(backend="redis", client=Dead())
    await _put(store)
    assert await store.get("a.example") is not None


async def test_live_clearance_replays_as_solved_t0(monkeypatch: pytest.MonkeyPatch) -> None:
    await clearance.store().put("a.example", {"cf_clearance": CF}, UA, "T1")
    seen: list[str] = []

    async def replay(item: clearance.Clearance, url: str, remaining: float) -> str:
        seen.append(item.user_agent)
        return "<html>real content</html>"

    async def boom(url: str, remaining: float) -> tuple[str | None, str]:
        raise AssertionError("t0 fetch must not run when a clearance replays")

    monkeypatch.setattr(lanes, "_cached", replay)
    monkeypatch.setattr(lanes.t0_profile, "fetch_clean", boom)
    outcome = await lanes._t0(CHALLENGE, 5.0)
    assert outcome.outcome == "solved"
    assert outcome.html == "<html>real content</html>"
    assert seen == [UA]


async def test_challenge_on_replay_invalidates_and_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await clearance.store().put("a.example", {"cf_clearance": CF}, UA, "T1")
    called: list[str] = []

    async def replay(item: clearance.Clearance, url: str, remaining: float) -> str:
        return "<html>Just a moment...</html>"

    async def fetch(url: str, remaining: float) -> tuple[str | None, str]:
        called.append(url)
        return None, "unsolved"

    monkeypatch.setattr(lanes, "_cached", replay)
    monkeypatch.setattr(lanes.t0_profile, "fetch_clean", fetch)
    outcome = await lanes._t0(CHALLENGE, 5.0)
    assert outcome.outcome == "unsolved"
    assert called == ["https://a.example/page"]
    assert await clearance.store().get("a.example") is None


async def test_disabled_store_leaves_t0_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_CAPTCHA_CLEARANCE_ENABLED", "0")
    called: list[str] = []

    async def fetch(url: str, remaining: float) -> tuple[str | None, str]:
        called.append(url)
        return "<html>plain</html>", "solved"

    def never() -> clearance.ClearanceStore:
        raise AssertionError("store must not be consulted when disabled")

    monkeypatch.setattr(lanes.t0_profile, "fetch_clean", fetch)
    monkeypatch.setattr(lanes.clearance, "store", never)
    outcome = await lanes._t0(CHALLENGE, 5.0)
    assert outcome.outcome == "solved"
    assert outcome.html == "<html>plain</html>"
    assert called == ["https://a.example/page"]


async def test_flaresolverr_solve_stores_the_clearance(monkeypatch: pytest.MonkeyPatch) -> None:
    token = json.dumps(
        {"cookies": [{"name": "cf_clearance", "value": CF, "domain": "a.example"}], "userAgent": UA}
    )

    async def solve(url: str, timeout_s: float) -> FlareSolution:
        return FlareSolution(ok=True, html="<html>real</html>", token=token, elapsed_ms=5)

    monkeypatch.setattr(lanes, "flaresolverr_fetch", solve)
    outcome = await lanes._t1(CHALLENGE, 5.0)
    assert outcome.outcome == "solved"
    stored = await clearance.store().get("a.example", user_agent=UA)
    assert stored is not None
    assert stored.cf_clearance == CF
    assert stored.source_tier == "T1"
    assert stored.cookie_header() == f"cf_clearance={CF}"


def test_domain_key_drops_port_and_case() -> None:
    assert clearance.domain_of("https://A.Example:8443/path?q=1") == "a.example"
