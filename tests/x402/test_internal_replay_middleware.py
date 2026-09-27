"""Replay-protection cover for the internal free path — skew + binding half.

Regression guard for the 2026-09-27 gap: the internal credential was a bare
HMAC over ``METHOD\\npath\\ncaller``, so one captured request stayed valid for
that endpoint forever. It now also carries a signed ``X-Internal-Timestamp``
checked against ``PRY_INTERNAL_MAX_SKEW_SECONDS`` (default 300) plus a
TTL-evicting seen-signature cache.

Sibling of ``test_internal_freshness_middleware.py`` (window + cache half),
which also owns the shared scaffolding; and of
``test_internal_gate_middleware.py`` (gate-level cover that predates the
timestamp header).
"""

import pytest

from pry.payments.x402_middleware.internal import (
    INTERNAL_TIMESTAMP_HEADER,
    internal_max_skew,
    internal_request,
)
from tests.x402.test_internal_freshness_middleware import (
    _assert_challenged,
    _assert_served,
    _call,
    _configure,
    _headers,
    _now,
    _scope,
    _StubApp,
)

# ── PRY_INTERNAL_MAX_SKEW_SECONDS ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_skew_env_widens_and_narrows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured skew governs the window on both sides of the default."""
    _configure(monkeypatch, skew="60")
    assert internal_max_skew() == 60
    stale = _now(-120)
    app = _StubApp()
    _assert_challenged(app, await _call(app, _headers(stale)))
    _configure(monkeypatch, skew="600")
    wider = _StubApp()
    _assert_served(wider, await _call(wider, _headers(stale)))


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["abc", "0", "-30", "  ", "3.5"])
async def test_bad_skew_env_fails_closed(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """A junk skew setting must reject everything, never widen the window."""
    _configure(monkeypatch, skew=bad)
    assert internal_max_skew() == 0
    app = _StubApp()
    _assert_challenged(app, await _call(app, _headers(_now())))


def test_unset_skew_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent setting means the documented 300s window."""
    monkeypatch.delenv("PRY_INTERNAL_MAX_SKEW_SECONDS", raising=False)
    assert internal_max_skew() == 300


# ── Binding ──────────────────────────────────────────────────────────────────


def test_timestamp_is_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signature minted for one timestamp must not validate under another."""
    _configure(monkeypatch)
    now = _now()
    good = dict(_headers(now))
    scope = _scope([])
    assert internal_request(scope, good) is True
    swapped = dict(good)
    swapped[INTERNAL_TIMESTAMP_HEADER] = _now(1).encode()
    assert internal_request(scope, swapped) is False
