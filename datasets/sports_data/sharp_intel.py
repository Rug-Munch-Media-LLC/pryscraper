"""Sharp money intelligence — thin facade over focused submodules.

Professional bettors read the market through four lenses, approximated here
from free sources (The Odds API via ``PRY_ODDS_API_KEY`` with an ESPN
fallback for the slate, plus an optional public-betting-percentage feed via
``PRY_SHARP_BET_FEED``):

1. **Steam moves** (:mod:`datasets.sports_data.sharp_steam`) — a line that
   moved across 3+ books inside a short window.
2. **Reverse line movement** (:mod:`datasets.sports_data.sharp_rlm`) — the
   line moves toward the side the public is NOT on.
3. **Bet % vs money % divergence** (:mod:`datasets.sports_data.sharp_divergence`)
   — big bettors are where money % exceeds bet %.
4. **Line watch** (:mod:`datasets.sports_data.sharp_watch`) — current vs
   opening line per book, best available number, value indicator.

[REVIEW] Feasibility flag: there is **no stable no-auth public API** for
per-event public betting percentages as of 2026. The bet-percentage paths
(RLM, divergence) depend on ``PRY_SHARP_BET_FEED``; when unconfigured they
return ``[]`` — they never fabricate percentages. Steam moves and line
watch work from odds alone.

Contract: all public functions are async, never raise, and return ``[]`` /
``{}`` on failure.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.sharp_common import now_iso
from datasets.sports_data.sharp_divergence import get_bet_vs_money_divergence
from datasets.sports_data.sharp_rlm import get_reverse_line_movement
from datasets.sports_data.sharp_steam import get_steam_moves
from datasets.sports_data.sharp_watch import get_line_watch

__all__ = [
    "get_bet_vs_money_divergence",
    "get_consensus_sharp_picks",
    "get_line_watch",
    "get_reverse_line_movement",
    "get_sharp_report",
    "get_steam_moves",
]


# ── Sharp report ───────────────────────────────────────────────────────
async def get_sharp_report(sport: str = "nba") -> dict[str, Any]:
    """Full sharp money report: steam + RLM + divergence + line watch.

    Returns:
        Report dict with counts, top signals, and overall sharp indicators
        (games with the most aligned sharp signals), or ``{}`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return {}
    steam = await get_steam_moves(normalized)
    rlm = await get_reverse_line_movement(normalized)
    divergence = await get_bet_vs_money_divergence(normalized)
    watch = await get_line_watch(normalized)
    if not (steam or rlm or divergence or watch):
        return {}
    # Overall sharp indicators: events touched by the most signal types.
    tally: dict[str, dict[str, Any]] = {}
    for kind, items, gated in (
        ("steam", steam, False),
        ("rlm", rlm, False),
        ("divergence", divergence, True),
    ):
        for item in items:
            if gated and not item.get("sharp_side"):
                continue
            entry = tally.setdefault(
                str(item.get("event") or ""), {"signals": set(), "event": item.get("event")}
            )
            entry["signals"].add(kind)
    overall = sorted(
        (
            {"event": entry["event"], "signals": sorted(entry["signals"])}
            for entry in tally.values()
            if entry["signals"]
        ),
        key=lambda item: -len(item["signals"]),
    )
    return {
        "sport": normalized,
        "generated_at": now_iso(),
        "steam_moves_count": len(steam),
        "rlm_signals": len(rlm),
        "top_divergences": divergence[:5],
        "line_watch_items": len(watch),
        "steam_moves": steam[:10],
        "rlm": rlm[:10],
        "overall_sharp_indicators": overall[:10],
    }


# ── Consensus sharp picks ──────────────────────────────────────────────
async def get_consensus_sharp_picks(sport: str = "nba") -> list[dict[str, Any]]:
    """Games where multiple sharp indicators align on the same side.

    Returns:
        List of consensus dicts: event, indicators fired, sharp_pick side,
        confidence_level, recommended_bet. ``[]`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    steam = await get_steam_moves(normalized)
    rlm = await get_reverse_line_movement(normalized)
    divergence = await get_bet_vs_money_divergence(normalized)
    picks: dict[str, dict[str, Any]] = {}

    def _entry(event: str, event_id: str) -> dict[str, Any]:
        return picks.setdefault(
            event, {"event": event, "event_id": event_id, "indicators": [], "sides": []}
        )

    for item in steam:
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("steam")
        entry["sides"].append(str(item.get("outcome") or ""))
    for item in rlm:
        if not item.get("rlm_signal"):
            continue
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("rlm")
        entry["sides"].append(str(item.get("side") or ""))
    for item in divergence:
        sharp_side = item.get("sharp_side")
        if not sharp_side:
            continue
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("divergence")
        entry["sides"].append(str(sharp_side))

    results: list[dict[str, Any]] = []
    for event, entry in picks.items():
        indicators = entry["indicators"]
        if len(indicators) < 2:
            continue
        sides = [side for side in entry["sides"] if side]
        aligned = len(set(sides)) == 1 and len(sides) == len(indicators)
        confidence_level = (
            "high" if (len(indicators) >= 3 and aligned) else ("medium" if aligned else "low")
        )
        results.append(
            {
                "event": event,
                "event_id": entry["event_id"],
                "sport": normalized,
                "indicators": indicators,
                "sharp_pick": sides[0] if aligned and sides else None,
                "confidence_level": confidence_level,
                "recommended_bet": (
                    f"{'Side: ' + str(sides[0]) if aligned and sides else 'Watch only'} "
                    f"({len(indicators)} sharp indicators)"
                ),
            }
        )
    results.sort(key=lambda item: -len(item.get("indicators") or []))
    return results
