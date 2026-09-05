"""Static player-props tables + market resolution helpers.

The tables (user-facing market aliases, human-readable labels, per-sport
default market sets, ESPN estimate rules) live as plain JSON under
``data/props.json`` — data, not code. This module loads them at import time.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets.sports_data.odds import _SPORT_ALIASES, _SPORTS

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


_TABLES = _load_json("props.json")

# User-facing market name -> The Odds API player-props market key.
_MARKET_ALIASES: dict[str, str] = _TABLES["market_aliases"]

# Human-readable label per prop market (used by get_prop_markets). Any
# market key without an entry falls back to a title-cased key.
_PROP_LABELS: dict[str, str] = _TABLES["prop_labels"]

# Default market set queried when ``market="all"``. Kept small: each market
# in a call counts against the Odds API free-tier quota.
_PROP_MARKETS: dict[str, list[str]] = _TABLES["prop_markets"]

# ESPN stat-label fragment -> prop market, per sport, for the estimate
# fallback. Only per-game averages translate cleanly to a line.
_ESTIMATE_RULES: dict[str, list[tuple[str, str]]] = {
    sport: [(fragment, market) for fragment, market in rules]
    for sport, rules in _TABLES["estimate_rules"].items()
}


def _short_slug(slug: str) -> str:
    """Map a resolved slug (alias or canonical Odds API key) to a config key.

    ``_resolve_sports`` returns whatever the caller passed — both ``"nba"``
    and ``"basketball_nba"`` resolve. Per-sport tables here are keyed by the
    short alias, so canonical keys are folded back onto their alias.
    """
    if slug in _PROP_MARKETS or slug in _ESTIMATE_RULES:
        return slug
    odds_key = _SPORTS[slug][0]
    for alias, canonical in _SPORT_ALIASES.items():
        if canonical == odds_key:
            return alias
    return slug


def _market_keys_for(sport: str, market: str) -> list[str]:
    """Return the list of Odds API market keys for a ``market`` request.

    Accepts a single market name (``"points"``, a raw Odds API key such as
    ``"player_sacks"``) or a comma/pipe separated list (``"points,rebounds"``).
    ``"all"`` (default) uses the per-sport default set in ``_PROP_MARKETS``.
    """
    raw = str(market or "").strip().lower()
    if raw in {"", "all"}:
        return list(_PROP_MARKETS.get(_short_slug(sport), []))
    keys: list[str] = []
    for part in raw.replace("|", ",").split(","):
        part = part.strip()
        if not part or part in {"all", "*"}:
            continue
        key = _MARKET_ALIASES.get(part, part)
        if not key.startswith("player_"):
            continue
        if key not in keys:
            keys.append(key)
    return keys


def _prop_label(market_key: str) -> str:
    """Human-readable label for a prop market key (fallback: title-cased)."""
    label = _PROP_LABELS.get(market_key)
    if label:
        return label
    return " ".join(
        part.capitalize() for part in str(market_key or "").replace("player_", "", 1).split("_")
    )
