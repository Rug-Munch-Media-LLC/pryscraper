"""Pry — the tier gate: a dead URL answers without waking a tier.

The tier ladder is bounded per call, but nothing told a caller to stop asking
about a URL that has never worked. ``url_terminal_state`` holds that fact; this
module is the only seam the scrape path needs, so the orchestrator stays a
"few calls" change instead of importing a state machine it does not own.

``pre_tier_check`` runs BEFORE any tier (and before the domain semaphore): a
terminal URL returns a structured failure naming the verdict, so the caller
gets the same shape it gets from the ladder while no browser, proxy or solver
slot is spent. ``post_tier_outcome`` is called once per attempt with the
payload (or ``None`` when the attempt raised), so consecutive failures
accumulate and one success clears them.

Success is ``status == "ok"`` — the status this engine's ``_result`` returns —
NOT ``"success"``. The two differ, and testing the wrong one is not a cosmetic
bug: every winning scrape would count as a failure, so the third success of a
perfectly healthy URL would make that URL terminal. Only a payload carrying a
``verdict`` is evidence about the target: an invalid-URL error never ran the
ladder and must not spend a URL's failure budget.

Neither function raises: a broken gate must degrade to "try the tier", never
to a 500 on a scrape that would otherwise work.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import logging
from typing import Any

from pry.engine import url_terminal_state

logger = logging.getLogger(__name__)


def _terminal_result(url: str, reason: str) -> dict[str, Any]:
    """The structured failure a terminal URL returns instead of a tier run."""
    return {
        "status": "error",
        "verdict": "url_terminal",
        "url": url,
        "error": reason,
        "content": "",
        "tiers_attempted": [],
        "tiers_failed": [],
        "tiers_skipped": [],
        "blame_tier": False,
    }


def pre_tier_check(url: str) -> dict[str, Any] | None:
    """Return the terminal short-circuit result for ``url``, or None to proceed."""
    try:
        reason = url_terminal_state.terminal_reason(url)
    except Exception:  # a broken gate must not break a scrape
        logger.debug("url_gate_precheck_failed", exc_info=True)
        return None
    if reason is None:
        return None
    logger.info("url_terminal_short_circuit", extra={"url": url, "reason": reason})
    return _terminal_result(url, reason)


def _is_success(result: dict[str, Any]) -> bool:
    """True when the ladder returned a win (``_result`` sets ``status: ok``)."""
    return result.get("status") == "ok"


def post_tier_outcome(url: str, result: dict[str, Any] | None) -> None:
    """Count this attempt's outcome so a dead URL eventually becomes terminal.

    ``result`` is the scrape payload, or ``None`` when the attempt raised.
    """
    try:
        if result is None:
            url_terminal_state.record_failure(url)
        elif _is_success(result):
            url_terminal_state.record_success(url)
        elif "verdict" in result:  # the ladder actually ran and lost
            url_terminal_state.record_failure(url)
    except Exception:  # bookkeeping never fails a scrape
        logger.debug("url_gate_post_outcome_failed", exc_info=True)


__all__ = ["post_tier_outcome", "pre_tier_check"]
