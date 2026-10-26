# SPDX-License-Identifier: MIT
# ruff: noqa: S608  # identifiers are constants; no user input reaches SQL
# Copyright (c) 2026 Rug Munch Media LLC
"""Ingest ``rugdex.pairs`` into ``rugdex.dextools_tokens`` - append only on change.

Source -> store (nothing else is guessed):

    chain, token_address  -> chain, address            (required)
    token_name            -> name                      (``''`` becomes NULL)
    token_symbol          -> symbol                    (``''`` becomes NULL)
    liquidity_usd         -> liquidity_usd
    (absent)              -> price_usd/volume/holders/taxes/socials/source_url = NULL

``rugdex.pairs`` was extracted with two columns misaligned: ``token_symbol``
holds a *price* (``0.014378``) and the ticker sits in ``token_name``
(``RAIN / USDT 0.3%``). We therefore:

* keep ``token_symbol`` verbatim only when it is not numeric;
* otherwise take the ticker from the left of `` / `` in ``name`` - a value the
  row actually states - and record ``quality='symbol_from_name'``;
* when the name has no pair separator, store ``symbol=NULL`` and
  ``quality='symbol_is_price'``. A price is never written into ``symbol``.

``name`` is preserved unchanged, so every derived ``symbol`` is traceable.
Idempotency: ``plan`` compares the mapped row with the latest stored row and
emits only real changes, so re-running the same snapshot inserts nothing.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.datasources.dextools_store import DextoolsStore

NUMERIC = re.compile(r"^[0-9][0-9.,eE+-]*$")
PAIRS = "rugdex.pairs"
COMPARED = ("symbol", "name", "liquidity_usd", "quality")


def pair_to_row(pair: dict[str, Any], fetched_at: str | None = None) -> dict[str, Any]:
    """Map one ``rugdex.pairs`` row to a store row; unknown fields stay ``None``."""
    name = (pair.get("token_name") or "").strip() or None
    raw_symbol = (pair.get("token_symbol") or "").strip() or None
    symbol, quality = raw_symbol, "ok"
    if not raw_symbol:
        symbol, quality = None, "no_symbol"
    elif NUMERIC.match(raw_symbol):
        head, separator, _pair = (name or "").partition(" / ")
        head = head.strip()
        if separator and head and not NUMERIC.match(head):
            symbol, quality = head, "symbol_from_name"
        else:
            symbol, quality = None, "symbol_is_price"
    return {
        "chain": (pair.get("chain") or "").strip(),
        "address": (pair.get("token_address") or "").strip().lower(),
        "symbol": symbol,
        "name": name,
        "price_usd": None,
        "liquidity_usd": pair.get("liquidity_usd"),
        "volume_24h_usd": None,
        "holders": None,
        "tax_buy": None,
        "tax_sell": None,
        "socials": [],
        "source_url": None,
        "quality": quality,
        "fetched_at": fetched_at or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000"),
    }


def plan(
    rows: list[dict[str, Any]], current: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    """Changed rows only: one row per key (highest liquidity), compared to the stored latest."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["chain"], row["address"])
        if not key[0] or not key[1]:
            continue
        candidate = best.get(key)
        if candidate is None or (row.get("liquidity_usd") or 0) > (
            candidate.get("liquidity_usd") or 0
        ):
            best[key] = row
    fresh: list[dict[str, Any]] = []
    for key, row in best.items():
        stored = current.get(key)
        if stored is not None and all(stored.get(field) == row.get(field) for field in COMPARED):
            continue
        fresh.append(row)
    return fresh


def read_pairs(store: DextoolsStore, limit: int = 5000) -> list[dict[str, Any]]:
    raw = store.sql(  # nosec B608 - constant query
        "SELECT chain, token_address, token_name, token_symbol, liquidity_usd"
        f" FROM {PAIRS} FINAL LIMIT {int(limit)} FORMAT JSONEachRow"
    )
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def ingest_pairs(store: DextoolsStore, fetched_at: str | None = None) -> dict[str, Any]:
    """Read pairs, append only changed rows, return read/inserted/skipped/visible counts."""
    before = store.count()
    rows = [pair_to_row(pair, fetched_at) for pair in read_pairs(store)]
    fresh = plan(rows, store.latest())
    inserted = store.insert(fresh)
    flags: dict[str, int] = {}
    for row in rows:
        flags[row["quality"]] = flags.get(row["quality"], 0) + 1
    return {
        "source": PAIRS,
        "table": "rugdex.dextools_tokens",
        "read": len(rows),
        "inserted": inserted,
        "skipped": len(rows) - inserted,
        "before": before,
        "after": store.count(),
        "quality": flags,
    }
