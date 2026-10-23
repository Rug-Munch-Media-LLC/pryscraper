"""Persistent storage for the per-tier health store (split from tier_health).

The policy (when to skip) and the storage (what is on disk) change for
different reasons, and :mod:`pry.engine.tier_health` ran into the 200-line cap.
Storage lives here; ``tier_health.report`` / ``should_skip`` keep their public
signatures.

``record()`` is handed ``stale_after_s`` and ``min_exec_ms`` explicitly rather
than importing them: the caller owns the settings (so a test can monkeypatch
them) and this module stays free of import cycles.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Separator between domain and tier in a storage key. A domain never contains
#: it, so a key is scoped iff it does.
SEP = "|"

#: Bumped when the *evidence rules* change. A store written under an older
#: policy is put on probation once instead of being trusted against the new one.
POLICY_VERSION = 2


def key(tier: str, domain: str | None) -> str:
    return f"{domain}{SEP}{tier}" if domain else tier


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return {}


def prune(data: dict[str, Any], now: float, *, scoped: bool, stale_after_s: float) -> None:
    """Drop expired entries and, on a domain write, legacy unscoped keys.

    A legacy key has no domain, so it cannot be applied to one; applying it to
    all is exactly the 2026-10 poisoning. Dropping it lets a deployment heal
    without a manual ``rm``.
    """
    for name in list(data):
        if name.startswith("_"):
            continue
        entry = data[name]
        if not isinstance(entry, dict):
            del data[name]
            continue
        seen = entry.get("last_seen")
        if isinstance(seen, (int, float)) and now - float(seen) > stale_after_s:
            del data[name]
            continue
        if scoped and SEP not in name and entry.get("scope") != "global":
            del data[name]


def probation(data: dict[str, Any], now: float, probation_s: float) -> None:
    """One-shot: stop old evidence throttling a ladder it was not gathered on.

    Zero-win counters are KEPT so ``report`` still shows the wasted time, but
    they cannot skip a tier until the window closes. The old evidence was
    collected while a missing browser counted as a loss and 3 losses disabled a
    rung for 14 days — that is not evidence about the fixed ladder.
    """
    if data.get("_policy") == POLICY_VERSION:
        return
    until = now + probation_s
    for name, entry in list(data.items()):
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        if int(entry.get("attempts", 0)) > 0 and int(entry.get("wins", 0)) == 0:
            entry["probation_until"] = until
    data["_policy"] = POLICY_VERSION


def record(
    tier: str,
    *,
    won: bool,
    cost_ms: float,
    path: Path,
    domain: str | None,
    unavailable: bool,
    stale_after_s: float,
    min_exec_ms: float,
    probation_s: float,
) -> None:
    """Record one tier attempt. Never raises — health is observability.

    ``unavailable`` marks an attempt that never reached the network because a
    dependency was missing. That is not a loss, and charging it to the tier is
    how a dependency gap becomes "this method does not work here". A
    sub-millisecond loss is the same fault seen from the other side, so it is
    counted separately as ``instant_fails``.
    """
    if unavailable:
        return
    try:
        now = time.time()
        data = load(path)
        prune(data, now, scoped=domain is not None, stale_after_s=stale_after_s)
        probation(data, now, probation_s)
        name = key(tier, domain)
        entry = data.get(name) or {}
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["wins"] = int(entry.get("wins", 0)) + int(bool(won))
        entry["losses"] = int(entry.get("losses", 0)) + int(not won)
        entry["cost_ms_total"] = round(float(entry.get("cost_ms_total", 0.0)) + cost_ms, 1)
        if not won and cost_ms < min_exec_ms:
            entry["instant_fails"] = int(entry.get("instant_fails", 0)) + 1
        entry["last_seen"] = now
        entry["scope"] = "domain" if domain else "global"
        if domain:
            entry["domain"] = domain
        data[name] = entry
        data["_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a half-written health file is worse than a stale one,
        # and this is written from a request path.
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            tmp = Path(fh.name)
        tmp.replace(path)
    except (OSError, TypeError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return
