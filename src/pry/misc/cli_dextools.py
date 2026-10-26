# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""``pry dextools search|ingest|scrape`` - one store, one search implementation."""

from __future__ import annotations

import json

import click

from pry.datasources.dextools_ingest import ingest_pairs
from pry.datasources.dextools_scrape import scrape_dextools
from pry.datasources.dextools_store import open_store, search_or_refusal


@click.group(name="dextools")
def dextools_group() -> None:
    """Dextools: search our local store; scrape only robots-allowed pages."""


@dextools_group.command(name="search")
@click.argument("query")
@click.option("--chain", default=None, help="Filter by chain slug (e.g. ether, arbitrum).")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def dextools_search_cmd(query: str, chain: str | None, limit: int, as_json: bool) -> None:
    """Search symbol, name or address in rugdex.dextools_tokens (FINAL)."""
    result = search_or_refusal(query, chain=chain, limit=limit)
    if result.get("error") == "refused":
        click.echo(json.dumps(result))
        raise SystemExit(2)
    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return
    click.echo(
        f"query={result['query']!r} chain={result['chain']} total={result['total']} "
        f"returned={result['returned']} backend={result['backend']}"
    )
    for row in result["rows"]:
        click.echo(
            f"{row['chain']:<10} {row.get('symbol') or '-':<14} {(row.get('name') or '-')[:34]:<34} "
            f"liq={row.get('liquidity_usd')} quality={row.get('quality')} "
            f"src={row.get('source_url') or 'NULL'}"
        )


@dextools_group.command(name="ingest")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def dextools_ingest_cmd(as_json: bool) -> None:
    """Ingest rugdex.pairs into rugdex.dextools_tokens (idempotent)."""
    summary = ingest_pairs(open_store())
    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return
    click.echo(
        f"source={summary['source']} read={summary['read']} inserted={summary['inserted']} "
        f"skipped={summary['skipped']} total={summary['after']} quality={summary['quality']}"
    )


@dextools_group.command(name="scrape")
@click.option("--url", "urls", multiple=True, required=True, help="Allowed dextools.io page URL.")
@click.option("--limit", default=200, show_default=True, type=int)
def dextools_scrape_cmd(urls: tuple[str, ...], limit: int) -> None:
    """Scrape robots-allowed pages; a blocked or empty run exits non-zero."""
    summary = scrape_dextools(list(urls), limit=limit)
    click.echo(
        f"ingested={summary['ingested']} total={summary['total']} refused={summary['refused']}"
    )
    for refusal in summary["refusals"]:
        click.echo(json.dumps(refusal))
    if summary["ingested"] == 0:
        raise SystemExit(3)
