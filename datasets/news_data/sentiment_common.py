"""Shared helpers + lexicons for news sentiment scoring.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import re
from typing import Any

_POSITIVE_WORDS = frozenset(
    {
        "surge",
        "surges",
        "surged",
        "soar",
        "soars",
        "soared",
        "rally",
        "rallies",
        "rallied",
        "jump",
        "jumps",
        "jumped",
        "gain",
        "gains",
        "gained",
        "record",
        "records",
        "high",
        "higher",
        "highest",
        "up",
        "rise",
        "rises",
        "rose",
        "bullish",
        "bull",
        "breakout",
        "breakthrough",
        "win",
        "wins",
        "won",
        "beat",
        "beats",
        "outperform",
        "outperforms",
        "growth",
        "growing",
        "strong",
        "stronger",
        "strongest",
        "positive",
        "profit",
        "profits",
        "profitable",
        "boost",
        "boosts",
        "boosted",
        "upgrade",
        "upgrades",
        "upgraded",
        "approve",
        "approves",
        "approved",
        "approval",
        "adoption",
        "adopted",
        "launch",
        "launches",
        "launched",
        "milestone",
        "partnership",
        "partners",
        "success",
        "successful",
        "optimistic",
        "upbeat",
        "green",
        "climb",
        "climbs",
        "climbed",
        "advance",
        "advances",
        "advanced",
        "momentum",
        "demand",
        "inflow",
        "inflows",
        "accumulate",
        "accumulation",
        "support",
        "supports",
        "supported",
        "recovery",
        "recovers",
        "rebound",
        "rebounds",
        "stable",
        "stability",
        "bullishness",
        "flourish",
        "flourishing",
        "boom",
        "booming",
        "break",
        "breaks",
        "winner",
        "winners",
        "best",
        "top",
        "exceed",
        "exceeds",
        "exceeded",
        "expansion",
        "expanding",
    }
)

_NEGATIVE_WORDS = frozenset(
    {
        "crash",
        "crashes",
        "crashed",
        "plunge",
        "plunges",
        "plunged",
        "dump",
        "dumps",
        "dumped",
        "slump",
        "slumps",
        "slumped",
        "drop",
        "drops",
        "dropped",
        "fall",
        "falls",
        "fell",
        "decline",
        "declines",
        "declined",
        "low",
        "lower",
        "lowest",
        "down",
        "bearish",
        "bear",
        "selloff",
        "sell-off",
        "sell",
        "sells",
        "sold",
        "loss",
        "losses",
        "loses",
        "losing",
        "lose",
        "weak",
        "weaker",
        "weakest",
        "negative",
        "fear",
        "fears",
        "panic",
        "panics",
        "panicked",
        "worry",
        "worries",
        "worried",
        "risk",
        "risks",
        "risky",
        "fraud",
        "scam",
        "scams",
        "hack",
        "hacks",
        "hacked",
        "hacking",
        "exploit",
        "exploits",
        "exploited",
        "breach",
        "breaches",
        "breached",
        "steal",
        "steals",
        "stolen",
        "theft",
        "thief",
        "lawsuit",
        "lawsuits",
        "sue",
        "sues",
        "sued",
        "ban",
        "bans",
        "banned",
        "crackdown",
        "crackdowns",
        "warning",
        "warnings",
        "warn",
        "warns",
        "warned",
        "investigation",
        "investigations",
        "investigate",
        "investigates",
        "investigated",
        "probe",
        "probes",
        "probed",
        "fine",
        "fines",
        "fined",
        "penalty",
        "penalties",
        "sanction",
        "sanctions",
        "sanctioned",
        "collapse",
        "collapses",
        "collapsed",
        "bankrupt",
        "bankruptcy",
        "insolvent",
        "liquidation",
        "liquidated",
        "freeze",
        "freezes",
        "frozen",
        "seize",
        "seizes",
        "seized",
        "halt",
        "halts",
        "halted",
        "suspend",
        "suspends",
        "suspended",
        "suspension",
        "delist",
        "delists",
        "delisted",
        "reject",
        "rejects",
        "rejected",
        "rejection",
        "concern",
        "concerns",
        "concerned",
        "outflow",
        "outflows",
        "withdraw",
        "withdraws",
        "withdrawn",
        "withdrawal",
        "withdrawals",
        "red",
        "worst",
        "lost",
        "downfall",
        "setback",
        "setbacks",
        "trouble",
        "troubles",
        "struggle",
        "struggles",
        "struggled",
        "volatile",
        "volatility",
        "uncertainty",
        "doubt",
        "doubts",
        "doubted",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]+")


def _keyword_tone(text: str) -> float:
    """Score ``text`` -100..100 from a lightweight positive/negative lexicon.

    Ratio-based: ``100 * (pos - neg) / (pos + neg)`` when any signal words
    are present, otherwise ``0.0``.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    if not tokens:
        return 0.0
    positive = sum(1 for t in tokens if t in _POSITIVE_WORDS)
    negative = sum(1 for t in tokens if t in _NEGATIVE_WORDS)
    if positive + negative == 0:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * (positive - negative) / (positive + negative)))


def _tone_compound(tone_field: Any) -> float | None:
    """Extract GDELT's compound tone (first of the Tone column's values).

    GDELT's ``Tone`` column is a comma-separated list whose first value is
    the overall ``-100..100`` sentiment score. Returns ``None`` when the
    field is absent or not numeric.
    """
    if not isinstance(tone_field, str) or not tone_field.strip():
        return None
    first = tone_field.split(",", 1)[0].strip()
    try:
        return float(first)
    except ValueError:
        return None


def _article_tone(title: str, tone_field: Any) -> float:
    """Per-article tone: GDELT compound when present, keyword score otherwise."""
    gdelt_tone = _tone_compound(tone_field)
    if gdelt_tone is not None:
        return max(-100.0, min(100.0, gdelt_tone))
    return _keyword_tone(title)


def _date_key(published: str) -> str:
    """Extract ``YYYY-MM-DD`` from a parsed ISO timestamp ('' when absent)."""
    return published[:10] if len(published) >= 10 else ""
