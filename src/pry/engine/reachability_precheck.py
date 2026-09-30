"""Non-fatal target-reachability precheck for the scrape path.

The classifier already exists (``scripts/target_reachability.py``) but nothing
called it, so an unreachable target was indistinguishable from a scrape error
and the operator rebuilt a ladder that was never the problem.

Two facts make this module thin. First, it is loaded by PATH: the classifier
lives under ``scripts/`` and ``pry`` is installed editable, so importing it by
name would only work when the repo root is on ``sys.path``. Second, a precheck
that can break a scrape is worse than no precheck, so every outcome that is not
a confident ``UNREACHABLE`` degrades to ``UNKNOWN`` and changes nothing.

The verdict attaches to the FAILURE result only. A successful scrape never
touches this module's output, so no reachable target can have its tier order
altered by a probe.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from types import ModuleType

logger = logging.getLogger(__name__)

#: A hard cap well under the scrape budget: a slow probe must not eat the
#: chain's own 45s window, and must not delay a verdict we do not need.
PRECHECK_TIMEOUT_S = 3.0
#: The port the scrape path dials, so a closed :443 is reported as the target
#: being unreachable rather than as a refusal on a port nobody asked for.
#: The default only — a URL carrying an explicit port wins.
_TARGET_PORT = 443

_MODULE_NAME = "target_reachability"
_UNKNOWN: dict[str, Any] = {"reachability": "unknown", "blame_tier": False}


def _load_classifier() -> ModuleType | None:
    """Import the classifier by path, or None when it is not shipped."""
    module = sys.modules.get(_MODULE_NAME)
    if module is not None:
        return module
    path = Path(__file__).resolve().parents[3] / "scripts" / "target_reachability.py"
    try:
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # Register BEFORE exec: @dataclass resolves annotations through
        # sys.modules[cls.__module__], so executing first raises
        # AttributeError('NoneType' has no attribute '__dict__'). That is the
        # whole reason this loader is not a bare spec_from_file_location.
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001 - never let loading break a scrape
        logger.debug("reachability_module_unavailable", extra={"error": str(e)[:200]})
        return None
    return module


async def reachability_verdict(
    url: str,
    *,
    budget_s: float = PRECHECK_TIMEOUT_S,
) -> dict[str, Any]:
    """Classify the TARGET, or UNKNOWN. Never raises, always fast.

    ``budget_s`` is a wall-clock CAP, not a socket timeout to tune — the whole
    point is that a slow probe cannot hold a scrape open, so the name says
    which of the two it is.
    """
    try:
        classifier = _load_classifier()
        if classifier is None:
            return dict(_UNKNOWN)
        host = classifier.host_of(url)
        if not host:
            return dict(_UNKNOWN)
        # The port comes from the URL, resolved at CALL time so the default
        # cannot be pinned to the import-time constant: a precheck that dialled
        # a port nobody requested reports a fabricated UNREACHABLE.
        # Keyword args deliberately — precheck_dns_and_tcp's second positional
        # is the PORT, so a positional budget would be dialled as a port.
        # Note the live probe has no HTTP leg, so it can never itself return
        # REFUSING; that verdict comes from the scrape's own observed status.
        port = urlsplit(url).port or _TARGET_PORT
        async with asyncio.timeout(budget_s):
            reach = await asyncio.to_thread(
                classifier.precheck_dns_and_tcp, host, port, timeout=budget_s
            )
        verdict = classifier.classify(reach, host)
    except Exception as e:  # noqa: BLE001 - a probe must never fail a scrape
        logger.debug("reachability_precheck_failed", extra={"error": str(e)[:200]})
        return dict(_UNKNOWN)
    return {
        "reachability": str(verdict),
        "blame_tier": bool(classifier.blame_tier(verdict)),
    }
