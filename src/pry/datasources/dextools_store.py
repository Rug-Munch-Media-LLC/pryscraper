# SPDX-License-Identifier: MIT
# ruff: noqa: S608  # identifiers are module constants; every value passes through lit()
# Copyright (c) 2026 Rug Munch Media LLC
"""Dextools store: ClickHouse ``rugdex.dextools_tokens`` (typed refusals, FINAL reads).

    CREATE TABLE rugdex.dextools_tokens (
      chain LowCardinality(String), address String,
      symbol Nullable(String), name Nullable(String),
      price_usd Nullable(Float64), liquidity_usd Nullable(Float64),
      volume_24h_usd Nullable(Float64), holders Nullable(Int64),
      tax_buy Nullable(Float64), tax_sell Nullable(Float64),
      socials Array(String), source_url Nullable(String),
      quality LowCardinality(String) DEFAULT 'ok',
      fetched_at DateTime64(3, 'UTC')
    ) ENGINE = ReplacingMergeTree(fetched_at) ORDER BY (chain, address, fetched_at)

Semantics: one row per (chain, address, fetch). Writers append only when a
row's content changed (see ``dextools_ingest.plan``); readers take the LATEST
row per (chain, address), so a re-run never inflates the visible count.
``source_url``/price/volume/holders/taxes stay NULL when the producer has no
value for them - nothing is synthesized.

Privileges: ``rmi`` holds SELECT/INSERT/ALTER/OPTIMIZE on this table only, and
no CREATE anywhere in ``rugdex``; the DDL above is applied once by an admin.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pry.datasources.dextools_types import Refusal

CH_URL = os.environ.get("PRY_CLICKHOUSE_URL", "http://127.0.0.1:8123")
CH_USER = os.environ.get("PRY_CLICKHOUSE_USER", "rmi")
CH_PASS_FILE = os.environ.get("PRY_CLICKHOUSE_PASSWORD_FILE", "")
TABLE = os.environ.get("PRY_DEXTOOLS_TABLE", "rugdex.dextools_tokens")

COLUMNS: tuple[str, ...] = (
    "chain",
    "address",
    "symbol",
    "name",
    "price_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "holders",
    "tax_buy",
    "tax_sell",
    "socials",
    "source_url",
    "quality",
    "fetched_at",
)
SEARCH_COLUMNS = (
    "chain, address, symbol, name, price_usd, liquidity_usd, volume_24h_usd, "
    "holders, socials, source_url, quality, fetched_at"
)
#: Latest version of every token: the only shape searches and counts read.
LATEST = f"SELECT {SEARCH_COLUMNS} FROM {TABLE} FINAL ORDER BY fetched_at DESC LIMIT 1 BY (chain, address)"


def lit(value: Any) -> str:
    """ClickHouse literal. ``None`` stays ``NULL`` - never an empty-string stand-in."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ",".join(lit(item) for item in value) + "]"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


class DextoolsStore:
    """Thin ClickHouse transport plus the queries the search surface needs."""

    backend = "clickhouse"

    def _password(self) -> str:
        """Password from the env, else from the file the operator points at.

        The path is configuration (``PRY_CLICKHOUSE_PASSWORD_FILE``); no
        credential path is baked into the source.
        """
        if os.environ.get("PRY_CLICKHOUSE_PASSWORD"):
            return os.environ["PRY_CLICKHOUSE_PASSWORD"].strip()
        if not CH_PASS_FILE:
            return ""
        try:
            return Path(CH_PASS_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def sql(self, statement: str) -> str:
        """Run one statement; an HTTP error re-raises with the ClickHouse message."""
        request = urllib.request.Request(  # noqa: S310 - fixed loopback URL
            f"{CH_URL}/?database=default",
            data=statement.encode("utf-8"),
            headers={"X-ClickHouse-User": CH_USER, "X-ClickHouse-Key": self._password()},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310 - fixed loopback URL
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode("utf-8", "replace").strip()) from exc

    def ensure(self) -> None:
        self.sql(f"SELECT 1 FROM {TABLE} LIMIT 0")

    def count(self) -> int:
        """Visible rows: one per (chain, address), never the raw version count."""
        self.ensure()
        raw = self.sql(f"SELECT count() FROM ({LATEST}) FORMAT TSV").strip()
        return int(raw or 0)

    def latest(self) -> dict[tuple[str, str], dict[str, Any]]:
        self.ensure()
        raw = self.sql(f"{LATEST} FORMAT JSONEachRow")  # nosec B608 - identifiers are constants, values via lit()
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return {(row["chain"], row["address"]): row for row in rows}

    def insert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        values = ",".join(
            "(" + ",".join(lit(row.get(column)) for column in COLUMNS) + ")" for row in rows
        )
        self.sql(f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES {values}")
        return len(rows)

    def search(self, query: str, chain: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Case-insensitive substring match on symbol/name/address over the latest rows."""
        needle = query.replace("\\", "").replace("'", "")
        where = (
            "(positionCaseInsensitive(coalesce(symbol, ''), {q}) > 0"
            " OR positionCaseInsensitive(coalesce(name, ''), {q}) > 0"
            " OR positionCaseInsensitive(address, {q}) > 0)"
        ).replace("{q}", lit(needle))
        if chain:
            where += f" AND chain = {lit(chain)}"
        total = int(
            self.sql(f"SELECT count() FROM ({LATEST}) WHERE {where} FORMAT TSV").strip() or 0
        )
        raw = self.sql(
            f"SELECT * FROM ({LATEST}) WHERE {where}"
            f" ORDER BY liquidity_usd DESC NULLS LAST, chain, address LIMIT {int(limit)} FORMAT JSONEachRow"
        )
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return {
            "query": query,
            "chain": chain,
            "total": total,
            "returned": len(rows),
            "backend": self.backend,
            "rows": rows,
        }


def open_store() -> DextoolsStore:
    store = DextoolsStore()
    store.ensure()
    return store


def empty_store_refusal(store: DextoolsStore) -> dict[str, Any]:
    """Typed refusal for an empty store - never a silent ``[]``."""
    return Refusal(
        code="unavailable",
        reason="dextools store is empty - run `pry dextools ingest` first",
        detail=f"table={TABLE} backend={store.backend}",
    ).to_dict()


def search_or_refusal(query: str, chain: str | None = None, limit: int = 20) -> dict[str, Any]:
    """The single search implementation shared by the CLI and the MCP tool."""
    store = open_store()
    if store.count() == 0:
        return empty_store_refusal(store)
    return store.search(query, chain=chain, limit=limit)
