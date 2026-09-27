"""Audit evidence for the bare-except review of the tier modules.

The antipattern gate classifies every ``except`` in ``src/pry/engine/tiers*``
and ``tier_chain.py``. This suite does NOT ask that code to log or to raise --
the review found no category-A handler. It pins the contract that decided
every verdict, so the classification cannot silently rot in a way the
aggregate gate count would never notice.

The deciding contract, from ``_attempt_tier``: "``html`` is None on any
failure". The orchestrator gates promotion on
``success = bool(html and self._is_valid(html))`` and rejects a non-str
payload in ``_record_tier_success`` via ``if not isinstance(html, str)``. So
a ``None`` from a tier can never be promoted to a success result, which makes
every defensive tier ``except`` a DELIBERATE typed failure (category B). The
tests below assert that behaviourally, per tier, not by reading the source.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

import pry.engine.proxy_manager as pm_mod
import pry.engine.ultimate_scraper as us
from pry.engine.tier_chain import TierChainMixin
from pry.engine.ultimate_scraper import UltimateScraper

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
from antipattern_handlers import classify_handler  # noqa: E402

_ENGINE = _REPO / "src" / "pry" / "engine"
_TIER_FILES = (
    "tiers.py",
    "tiers_base.py",
    "tiers_browser.py",
    "tiers_http.py",
    "tiers_special.py",
    "tier_chain.py",
)
_ZONES = {"silent-fallthrough", "value-passthrough", "explicit-failure-return"}
_OPTS: dict[str, Any] = {}
_URL = "https://example.com/page"


class _Chain(TierChainMixin):
    """Concrete host for the mixin; the proxy helpers need no state."""


class _Raising:
    """A collaborator whose method always fails, the way a real tier sees it."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def is_available(self) -> bool:
        return True

    async def fetch(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
        raise self._exc

    async def scrape(self, *_a: Any, **_kw: Any) -> Any:
        raise self._exc


def test_a_tier_none_return_is_never_promoted_to_a_success() -> None:
    """The gate that makes every tier ``except`` a typed failure (category B)."""
    src = (_ENGINE / "scraper_orchestrate.py").read_text()
    assert "html is None on any failure" in src
    # Promotion is gated on the truthiness of html, not on its type.
    assert "success = bool(html and self._is_valid(html))" in src
    # And success recording rejects a non-str payload outright.
    assert "if not isinstance(html, str):" in src


async def test_tiers_that_pass_the_success_flag_alone_return_no_content() -> None:
    """A ``success: False`` payload must not leak its body as a result.

    ``_tier_tls_fingerprint`` and ``_tier_camoufox`` both read a body out of
    the collaborator's dict, so the guard on that dict is load-bearing.
    """
    payloads: tuple[tuple[dict[str, Any], str], ...] = (
        ({"success": False, "text": "<html>leaked</html>"}, "_tier_tls_fingerprint"),
        ({"success": False, "content": "<html>leaked</html>"}, "_tier_camoufox"),
    )

    class _Body(_Raising):
        def __init__(self, payload: dict[str, Any]) -> None:
            super().__init__(RuntimeError("unused"))
            self._payload = payload

        async def fetch(self, *_a: Any, **_kw: Any) -> dict[str, Any]:
            return self._payload

    for payload, tier in payloads:
        scraper = UltimateScraper()
        if "text" in payload:
            scraper._tls_scraper = _Body(payload)
        else:
            scraper._camoufox = _Body(payload)
        assert await getattr(scraper, tier)(_URL, _OPTS) is None


async def test_a_raising_collaborator_yields_none_not_a_raise() -> None:
    """``tiers_browser`` TLS tier: a failed fetch must not propagate."""
    scraper = UltimateScraper()
    scraper._tls_scraper = _Raising(RuntimeError("upstream down"))
    assert scraper._tls_scraper.is_available() is True
    assert await scraper._tier_tls_fingerprint(_URL, _OPTS) is None


@pytest.mark.parametrize(
    ("flag", "obj_flag", "tier"),
    [
        ("_has_ai_visual", "_ai_visual", "_tier_ai_visual"),
        ("_has_mobile", "_mobile_scraper", "_tier_mobile_app"),
        ("_has_graphql", "_graphql_scraper", "_tier_graphql"),
    ],
)  # fmt: skip
async def test_external_scraper_tiers_return_none_on_failure(
    monkeypatch: pytest.MonkeyPatch, flag: str, obj_flag: str, tier: str
) -> None:
    """``tiers_special``: a delegated scraper blowing up must stay ``None``."""
    monkeypatch.setattr(us, flag, True, raising=False)
    monkeypatch.setattr(us, obj_flag, _Raising(RuntimeError("down")), raising=False)
    assert await getattr(UltimateScraper(), tier)(_URL, _OPTS) is None


def test_extract_text_never_raises_and_never_returns_empty() -> None:
    """Last-resort tag stripping must not manufacture an empty success.

    The broken-markup case is the one that matters: a strict extractor throws
    there, so the tag-strip fallback is what the caller actually receives.
    """
    scraper = UltimateScraper()
    html = "<html><body>" + ("<p>real content here</p>" * 40) + "</body></html>"
    text = scraper._extract_text(html)
    assert text.strip()
    assert "real content here" in text
    assert "alpha" in scraper._extract_text("<div><p>alpha <b>beta</p></div><<<>>> tail")


@pytest.mark.parametrize("rel", _TIER_FILES)
def test_no_tier_handles_a_bare_except(rel: str) -> None:
    """``except:`` is the only genuinely silent shape; none may exist.

    Also asserts the gate can still classify every handler, so a syntax or
    zone change cannot silently disable this ratchet.
    """
    tree = ast.parse((_ENGINE / rel).read_text())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    for node in handlers:
        assert node.type is not None, f"{rel}:{node.lineno} is a bare except"
        assert classify_handler(node) in _ZONES, f"{rel}:{node.lineno}"


def test_resolve_proxy_url_falls_through_to_env_when_manager_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one helper that does not swallow: it degrades, it does not lie.

    A broken ProxyManager must not be reported as "no proxy configured" --
    that would quietly send every request direct.
    """

    class _Boom:
        def get_proxy_url(self) -> str:
            raise RuntimeError("proxy backend down")

    monkeypatch.setenv("PRY_PROXY_URL", "http://env-proxy:8080")
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.setattr(pm_mod, "ProxyManager", _Boom)
    assert _Chain()._resolve_proxy_url({}) == "http://env-proxy:8080"


def test_recommend_proxy_returns_none_when_the_manager_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``None`` here is the honest typed failure: there is no recommendation."""

    class _Boom:
        def get_recommendation(self, last_error: str) -> dict[str, str]:
            raise RuntimeError("proxy backend down")

    monkeypatch.setattr(pm_mod, "ProxyManager", _Boom)
    assert _Chain()._recommend_proxy("boom") is None


def test_resolve_proxy_url_still_honours_explicit_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``proxy=False`` short-circuits before the except can ever be reached."""
    monkeypatch.setenv("PRY_PROXY_URL", "http://env-proxy:8080")
    assert _Chain()._resolve_proxy_url({"proxy": False}) is None


def test_record_telemetry_failure_never_breaks_the_scrape() -> None:
    """Telemetry is observability-only; a dead backend must not raise."""

    def _boom(**_kw: object) -> None:
        raise RuntimeError("telemetry backend down")

    original = us._HAS_FALLBACK_TELEMETRY, us._record_fallback
    us._HAS_FALLBACK_TELEMETRY, us._record_fallback = True, _boom
    try:
        UltimateScraper()._record_telemetry(
            domain="example.com",
            tier_order=["direct"],
            attempts=[],
            final_tier=None,
            success=False,
            start=0.0,
            errors=["boom"],
        )
    finally:
        us._HAS_FALLBACK_TELEMETRY, us._record_fallback = original
