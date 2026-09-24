"""Token-based OFAC SDN name matching."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import re
from typing import Any

from datasets.legal_docs.sanctions.cache import _load_entries
from datasets.legal_docs.sanctions.entries import _join_name

logger = logging.getLogger(__name__)
_MAX_RESULTS = 50
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _norm(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.upper()).strip()


def _entry_name_pool(entry: dict[str, Any]) -> dict[str, str]:
    pool: dict[str, str] = {}
    primary = _join_name(entry.get("first_name"), entry.get("last_name"))
    if primary:
        pool["primary"] = _norm(primary)
    for index, aka in enumerate(entry.get("akas") or []):
        pool[f"aka{index}"] = _norm(aka)
    return pool


def _tokens(name: str) -> list[str]:
    return [token for token in _norm(name).split() if token]


async def screen_name(name: str) -> list[dict[str, Any]]:
    """Screen a name against the OFAC SDN list; never raises."""
    try:
        return await _screen_name(name)
    except Exception:
        logger.exception("legal_ofac_screen_crashed", extra={"name": name})
        return []


async def _screen_name(name: str) -> list[dict[str, Any]]:
    tokens = _tokens(name)
    if not tokens:
        return []
    entries = await _load_entries()
    if not entries:
        return []
    matches: list[dict[str, Any]] = []
    for entry in entries:
        pool = _entry_name_pool(entry)
        matched_fields = [
            label
            for label, normalized_name in pool.items()
            if all(token in normalized_name for token in tokens)
        ]
        if not matched_fields:
            continue
        matches.append(
            {
                "uid": entry.get("uid"),
                "name": _join_name(entry.get("first_name"), entry.get("last_name"))
                or (entry.get("akas") or [None])[0],
                "sdn_type": entry.get("sdn_type"),
                "programs": entry.get("programs") or [],
                "title": entry.get("title"),
                "remarks": entry.get("remarks"),
                "citizenships": entry.get("citizenships") or [],
                "akas": entry.get("akas") or [],
                "matched_fields": matched_fields,
                "matched_names": {label: pool[label] for label in matched_fields},
                "match_reason": (
                    f"all {len(tokens)} token(s) matched ({', '.join(sorted(matched_fields))})"
                ),
                "source": "ofac_sdn",
            }
        )
        if len(matches) >= _MAX_RESULTS:
            break
    matches.sort(key=lambda match: len(match.get("matched_names") or {}), reverse=True)
    return matches
