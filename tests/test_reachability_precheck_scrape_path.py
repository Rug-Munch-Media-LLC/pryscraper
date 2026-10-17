# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""A broken precheck must be invisible to the caller.

The hard constraint on the precheck: if it raises, times out, or cannot load,
the scrape proceeds exactly as before. That is proven here by RUNNING a scrape
and inspecting its result — not by asserting a mock called itself. The verdict
taxonomy itself is in ``test_reachability_precheck_verdicts``.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from pry.engine import reachability_precheck as rp
from pry.engine.ultimate_scraper import UltimateScraper
from scripts.target_reachability import Reachability, TargetProbe
from tests.reachability_precheck_helpers import (
    _install,
    _stub,
    _stub_raising,
)

HOST = "unreachable.invalid"
_URL = f"https://{HOST}/page"


def _one_tier_scraper(monkeypatch: pytest.MonkeyPatch, scraper: UltimateScraper) -> None:
    """Collapse the chain to one tier, so the test is about the precheck."""

    def _tiers(_url: str, *_a: Any, **_kw: Any) -> list[tuple[str, Any]]:
        return [("direct", None)]

    monkeypatch.setattr(scraper, "_build_tier_order", _tiers)


# ── The precheck cannot break a scrape ───────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("probe exploded"), TimeoutError("probe hung"), OSError("socket died")],
    ids=["raise", "timeout", "oserror"],
)
async def test_a_raising_precheck_leaves_a_successful_scrape_untouched(
    monkeypatch, exc: BaseException
) -> None:
    """The strongest witness: success never consults the precheck at all.

    A target that answers is not prechecked, so no probe — however broken —
    can alter its result.
    """
    scraper = UltimateScraper()
    _one_tier_scraper(monkeypatch, scraper)
    content = "<html><body>" + ("<p>real page content</p>" * 80) + "</body></html>"

    async def _succeed(_tier: str, *_a: Any, **_kw: Any) -> tuple[Any, float]:
        return content, 0.001

    monkeypatch.setattr(scraper, "_attempt_tier", _succeed)
    _install(monkeypatch, _stub_raising(exc))

    result = await scraper.scrape(_URL)
    assert result["status"] == "ok"
    assert result["method"] == "direct"
    assert "real page content" in result["content"]
    # A success carries no reachability fact, so there is nothing to misread.
    assert "target_reachability" not in result


async def test_a_raising_precheck_still_produces_a_normal_failure(monkeypatch) -> None:
    scraper = UltimateScraper()
    _one_tier_scraper(monkeypatch, scraper)

    async def _fail(_tier: str, *_a: Any, **_kw: Any) -> tuple[Any, float]:
        return None, 0.001

    monkeypatch.setattr(scraper, "_attempt_tier", _fail)
    _install(monkeypatch, _stub_raising(RuntimeError("probe exploded")))

    result = await scraper.scrape(_URL)
    assert result["status"] == "error"
    # Degrades to UNKNOWN, i.e. "we did not observe enough" — never a
    # fabricated UNREACHABLE, which would be reported as a fact about the target.
    assert result["target_reachability"] == Reachability.UNKNOWN
    assert result["blame_tier"] is False
    # The pre-existing failure payload is untouched.
    assert result["error"] == "direct_failed"
    expected = ["direct_failed"]
    assert result["tiers_failed"] == expected


async def test_failure_result_reports_the_reachability_fact(monkeypatch) -> None:
    """The wired value is a fact about the TARGET, added to the failure."""
    scraper = UltimateScraper()
    _one_tier_scraper(monkeypatch, scraper)

    async def _fail(_tier: str, *_a: Any, **_kw: Any) -> tuple[Any, float]:
        return None, 0.001

    monkeypatch.setattr(scraper, "_attempt_tier", _fail)
    _install(monkeypatch, _stub(TargetProbe(dns_ok=False, dns_error="no such host")))

    result = await scraper.scrape(_URL)
    assert result["status"] == "error"
    assert result["target_reachability"] == Reachability.UNREACHABLE
    assert result["blame_tier"] is False
    # Everything the caller already relied on is unchanged.
    assert result["error"] == "direct_failed"
    assert result["verdict"] == "exhausted"
    expected = ["direct"]
    assert result["tiers_attempted"] == expected


# ── Degradation is a fact about US, never about the target ───────────────


async def test_a_missing_classifier_degrades_to_unknown(monkeypatch) -> None:
    """Not shipped / not found on disk is a fact about US, not the target."""
    monkeypatch.setattr(rp, "_load_classifier", lambda: None)
    expected = {
        "reachability": Reachability.UNKNOWN,
        "blame_tier": False,
    }
    assert await rp.reachability_verdict(_URL) == expected


async def test_an_empty_host_degrades_to_unknown(monkeypatch) -> None:
    _install(monkeypatch, _stub(TargetProbe(dns_ok=False, dns_error="no such host")))
    expected = {
        "reachability": Reachability.UNKNOWN,
        "blame_tier": False,
    }
    assert await rp.reachability_verdict("not-a-url") == expected


async def test_a_hanging_probe_is_bounded_not_waited_on(monkeypatch) -> None:
    """Without the cap a black-holed host holds the scrape open indefinitely."""
    _install(monkeypatch, _stub(TargetProbe(dns_ok=False, dns_error="no such host")))

    async def _hang(*_a: Any, **_kw: Any) -> Any:
        await asyncio.sleep(30)

    monkeypatch.setattr(rp.asyncio, "to_thread", lambda *a, **kw: _hang())
    expected = {
        "reachability": Reachability.UNKNOWN,
        "blame_tier": False,
    }
    assert await rp.reachability_verdict(_URL, budget_s=0.01) == expected


# ── The loader is the lane's load-bearing seam ───────────────────────────


async def test_the_loader_actually_loads_the_shipped_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every other test stubs the loader away, so only this one can see it break.

    A silently-degrading loader is indistinguishable from a working one: if the
    path or the registration were wrong, all the stubbed tests would stay green
    while production returned UNKNOWN for every target, forever.
    """
    monkeypatch.delitem(sys.modules, rp._MODULE_NAME, raising=False)
    loaded = rp._load_classifier()
    assert loaded is not None
    assert loaded.host_of("https://site.example/x") == "site.example"
    # The real classifier, not a stub that merely looks like one. Compared as a
    # STRING: the loader makes a second copy of the file, so its Reachability
    # is a different class from the one imported here.
    assert str(loaded.classify(loaded.TargetProbe(dns_ok=False, dns_error="x"), "h")) == (
        Reachability.UNREACHABLE
    )


async def test_the_verdict_payload_survives_the_double_load() -> None:
    """Strings and bools only — no enum identity can leak out of the loader.

    Returning the enum would make ``verdict["reachability"] is Reachability.X``
    False for the loader's copy and True for a stub's: a trap that only bites
    in production, where the loader copy is the only one that runs.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delitem(sys.modules, rp._MODULE_NAME, raising=False)
    try:
        verdict = await rp.reachability_verdict("https://127.0.0.1:1/page", budget_s=0.5)
    finally:
        monkeypatch.undo()
    assert type(verdict["reachability"]) is str
    assert type(verdict["blame_tier"]) is bool
    assert verdict["reachability"] == str(Reachability.UNREACHABLE)
