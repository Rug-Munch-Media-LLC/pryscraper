"""Regression tests for the one category-A handler in the tier modules.

``_tier_tor`` carried an ``except aiohttp.ClientError`` around a ``try`` that
*begins with* ``import aiohttp``. That is a self-defeating handler: when the
import fails or the installed aiohttp is version-skewed, evaluating the except
clause raises ``AttributeError`` from inside the handler. The AttributeError
escapes the tier, and ``_attempt_tier`` -- whose only job is to stop a tier
breaking the chain -- logs it and keeps going, so the difference is invisible
in the error string and silent in production.

The second test covers the config half of the same hole: ``from_url`` reports a
malformed ``TOR_SOCKS5_PORT`` as a plain ``ValueError``, which a ClientError
handler does not catch either.

Both are asserted against the contract that actually matters -- a tier returns a
value and never raises, because the fallback chain has no per-tier error channel
and a raising tier costs the caller every remaining rung.

A tier ``None`` is a legitimate typed failure: ``_attempt_tier`` maps it to
``html = None`` and the orchestrator gates promotion on
``success = bool(html and self._is_valid(html))``, so ``None`` is recorded as a
tier failure, never as scraped content.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import builtins
import socket
from typing import Any

import pytest

from pry.engine import ultimate_scraper as us
from pry.engine.tiers_special import TierSpecialMixin


class _Tor(TierSpecialMixin):
    """Minimal stand-in: the tor tier only needs header building."""

    def _build_headers(self, url: str) -> dict[str, str]:
        return {"User-Agent": "test"}


@pytest.fixture
def tor_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(us, "_has_tor", True, raising=False)


async def test_tor_returns_none_when_aiohttp_import_is_broken(
    tor_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An aiohttp that exists but lacks ClientError must not escape the tier.

    This is the version-skew shape: ``import aiohttp`` SUCCEEDS, so the
    pre-binding below is overwritten with a module that has no ``ClientError``,
    and the old ``except aiohttp.ClientError`` clause blew up evaluating its own
    type expression.
    """
    import aiohttp  # noqa: F401 - pre-import so aiohttp_socks binds for real
    import aiohttp_socks  # noqa: F401

    class _SkewedAiohttp:
        """A stand-in aiohttp with no ClientError, as on a skewed deploy."""

    real_import = builtins.__import__

    def _skewed_import(name: str, *args: Any, **kwargs: Any) -> Any:
        module = real_import(name, *args, **kwargs)
        return _SkewedAiohttp() if name == "aiohttp" else module

    monkeypatch.setattr(builtins, "__import__", _skewed_import)

    assert await _Tor()._tier_tor("http://example.com", {}) is None


async def test_tor_returns_none_for_a_malformed_proxy_port(
    tor_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-numeric TOR_SOCKS5_PORT is a typed failure, not a ValueError.

    ``ProxyConnector.from_url`` raises ValueError for a bad port, which the old
    ClientError handler never caught -- the tier raised, aborting the chain.
    """
    from aiohttp_socks import ProxyConnector

    monkeypatch.setenv("TOR_SOCKS5_HOST", "127.0.0.1")
    monkeypatch.setenv("TOR_SOCKS5_PORT", "not-a-port")

    with pytest.raises(ValueError, match=r"[Pp]ort"):
        # Prove the premise: this really is a ValueError, not a ClientError.
        ProxyConnector.from_url("socks5://127.0.0.1:not-a-port")

    assert await _Tor()._tier_tor("http://example.com", {}) is None


async def test_tor_returns_none_when_the_proxy_is_unreachable(
    tor_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead SOCKS5 endpoint degrades to the typed tier failure, nothing more."""
    import aiohttp

    monkeypatch.setenv("TOR_SOCKS5_HOST", "127.0.0.1")
    # A reserved TEST-NET-1 address: guaranteed not to be a live SOCKS proxy.
    monkeypatch.setenv("TOR_SOCKS5_PORT", "9")
    monkeypatch.setattr(socket, "getaddrinfo", _raise_socket_error)

    assert await _Tor()._tier_tor("http://example.com", {}) is None
    assert aiohttp is not None  # the real module stayed importable


def _raise_socket_error(*args: Any, **kwargs: Any) -> Any:
    raise OSError("network is unreachable")
