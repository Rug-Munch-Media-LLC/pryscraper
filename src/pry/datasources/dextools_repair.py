# SPDX-License-Identifier: MIT
# ruff: noqa: S608  # identifiers are constants; no user input reaches SQL
# Copyright (c) 2026 Rug Munch Media LLC
"""Repair ``rugdex.pairs``: ticker back to ``token_symbol``, price to ``price_usd``.

The writer of ``rugdex.pairs`` is **not in any repository we hold** - the table
is filled by an external extraction, so the mapping cannot be fixed at source.
The documented downstream transformation applied here:

    token_symbol  a price (``0.01437804455``)   -> real ticker, left of `` / `` in token_name
    price         (stored in token_symbol)      -> new ``price_usd`` column
    source_url    absent on every row           -> canonical pair-explorer URL
    duplicates    10 rows share (chain,token)   -> newest ``created_at`` wins

``token_name`` is preserved verbatim, so every derived ticker stays traceable.
The repair is reversible: the untouched table survives as
``rugdex.pairs_unrepaired_<stamp>`` and ``down`` exchanges it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.datasources.dextools_store import DextoolsStore

PAIRS = "rugdex.pairs"
STAMP = "20261026"
BACKUP = f"{PAIRS}_unrepaired_{STAMP}"
STAGE = f"{PAIRS}_v2"
DEXTOOLS = "https://www.dextools.io/app"

CREATE = f"""
CREATE TABLE {STAGE} (
    chain String, pair_address String, token_address String, token_name String,
    token_symbol String, quote_token String, dex String, created_at DateTime,
    liquidity_usd Float64, fdv_usd Float64, price_usd Nullable(Float64), source_url String
) ENGINE = ReplacingMergeTree
ORDER BY (chain, pair_address)
TTL created_at + toIntervalDay(180)
SETTINGS index_granularity = 8192
"""

#: Newest row per (chain, token_address) - the 10 collisions drop to one each.
POPULATE = f"""
INSERT INTO {STAGE}
SELECT chain, pair_address, token_address, token_name,
    multiIf(position(token_name, ' / ') > 0
            AND trimBoth(splitByString(' / ', token_name)[1]) != '',
            trimBoth(splitByString(' / ', token_name)[1]),
            match(token_symbol, '^[0-9]'), '', token_symbol) AS token_symbol,
    quote_token, dex, created_at, liquidity_usd, fdv_usd,
    toFloat64OrNull(replaceAll(token_symbol, ',', '')) AS price_usd,
    concat('{DEXTOOLS}/', chain, '/pair-explorer/',
        if(startsWith(pair_address, concat(chain, '_')),
           substring(pair_address, length(chain) + 2), pair_address)) AS source_url
FROM (
    SELECT *, row_number() OVER (
        PARTITION BY chain, token_address ORDER BY created_at DESC, pair_address DESC
    ) AS rn
    FROM {PAIRS} FINAL
) WHERE rn = 1
"""

UP = [
    f"DROP TABLE IF EXISTS {STAGE}",
    CREATE,
    POPULATE,
    f"EXCHANGE TABLES {PAIRS} AND {STAGE}",
    f"RENAME TABLE {STAGE} TO {BACKUP}",
]
DOWN = [f"EXCHANGE TABLES {PAIRS} AND {BACKUP}"]

COUNTS = f"""
SELECT count() AS rows, uniqExact(chain, token_address) AS keys,
       countIf(price_usd > 0) AS priced, countIf(source_url != '') AS sourced,
       countIf(token_symbol NOT LIKE '%[0-9]%' OR token_symbol = '') AS tickers
FROM {PAIRS} FINAL
"""


def _run(store: DextoolsStore, statements: list[str]) -> None:
    for statement in statements:
        store.sql(statement)


def counts(store: DextoolsStore) -> dict[str, Any]:
    """Row/key census - valid before the repair, when price_usd/source_url do not exist yet."""
    raw = (
        store.sql(f"SELECT count(), uniqExact(chain, token_address) FROM {PAIRS} FINAL FORMAT TSV")
        .strip()
        .split("\t")
    )
    return dict(zip(("rows", "keys"), (int(value) for value in raw), strict=True))


def census(store: DextoolsStore) -> dict[str, Any]:
    """Post-repair census: rows, keys, priced rows, sourced rows, non-numeric tickers."""
    raw = store.sql(COUNTS.strip() + " FORMAT TSV").strip().split("\t")
    keys = ("rows", "keys", "priced", "sourced", "tickers")
    return dict(zip(keys, (int(value) for value in raw), strict=True))


def repair(store: DextoolsStore, direction: str = "up") -> dict[str, Any]:
    """Apply (``up``) or revert (``down``) the repair; return the census after it."""
    if direction not in {"up", "down"}:
        raise ValueError(f"direction must be 'up' or 'down', not {direction!r}")
    before = counts(store)
    _run(store, UP if direction == "up" else DOWN)
    return {"direction": direction, "before": before, "after": census(store)}
