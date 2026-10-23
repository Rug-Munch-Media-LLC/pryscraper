"""Pry — one scrape dispatch: URL gate, domain throttle, request span.

Extracted from ``scraper_orchestrate`` so that module keeps the fallback-chain
loop and nothing else. The order matters and is the whole point of the seam:

1. ``pre_tier_check`` runs FIRST, before the domain semaphore and before tier
   selection. A terminal URL returns the ladder's failure shape without
   occupying a concurrency slot, so a dead target cannot starve a live one.
2. The per-domain semaphore (``circuit_breaker.domain_semaphore``) is keyed on
   the registrable domain (``domain_key.memory_domain``), so spelling variants
   of one site share its cap.
3. ``post_tier_outcome`` runs once per attempt with the real payload — and also
   when the attempt RAISES, because an exception is evidence about the target
   as much as a returned error is. Counting only returned errors let a caller
   that retried on exceptions escape the URL cap entirely.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pry.core.observability import span
from pry.engine.circuit_breaker import domain_semaphore
from pry.engine.domain_key import memory_domain
from pry.engine.tier_terminal_gate import post_tier_outcome, pre_tier_check

#: ``(url, options) -> result`` — the orchestrator's fallback chain.
RunScrape = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]


def _annotate(request_span: Any, result: dict[str, Any]) -> None:
    """Copy the outcome onto the request span (no-op without a tracer)."""
    if request_span is None or not isinstance(result, dict):
        return
    request_span.set_attribute("pry.method", str(result.get("method", "")))
    # "ok" is the success status this engine returns (see _result); the span
    # previously tested for "success", so pry.success was false on every win.
    request_span.set_attribute("pry.success", result.get("status") == "ok")
    if isinstance(result.get("attempts"), list):
        request_span.set_attribute("pry.attempts", len(result["attempts"]))


async def dispatch_scrape(
    url: str,
    options: dict[str, Any] | None,
    run: RunScrape,
) -> dict[str, Any]:
    """Run one scrape through the terminal gate, domain throttle and span."""
    if (terminal := pre_tier_check(url)) is not None:
        return terminal
    async with domain_semaphore(memory_domain(url)):
        with span("scrape.request", {"http.url": url}) as request_span:
            try:
                result = await run(url, options)
            except BaseException:
                post_tier_outcome(url, None)
                raise
            post_tier_outcome(url, result)
            _annotate(request_span, result)
            return result


__all__ = ["RunScrape", "dispatch_scrape"]
