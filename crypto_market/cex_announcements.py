"""Binance announcement feed — secondary listing/delisting signal source.

Polls the free Binance CMS announcement feed for early listing/delisting
news before the ticker diff can see it. Best-effort; ignored on any
failure. Disable with the ``PRY_CEX_ANNOUNCEMENTS=0`` env var.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from crypto_market.cex_common import _ANNOUNCEMENTS_ENV, _fetch_json

logger = logging.getLogger(__name__)

_BINANCE_ANNOUNCEMENT_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
)
_BINANCE_ANNOUNCEMENT_PARAMS: dict[str, str] = {
    "type": "1",
    "pageNo": "1",
    "pageSize": "20",
    "blockType": "10000022",
    "sortType": "1",
}

# Words that look like ticker tokens in announcement titles but are not
# symbols (fallback tokenizer).
_ANNOUNCEMENT_TOKEN_STOP = frozenset(
    {
        "Binance",
        "Will",
        "List",
        "Delist",
        "With",
        "Tag",
        "Applied",
        "Seed",
        "New",
        "Adds",
        "Opens",
        "Trading",
        "For",
        "The",
        "Following",
        "Pairs",
        "And",
        "Starts",
        "Launchpool",
        "Earn",
        "Pre",
        "Market",
        "Official",
        "Support",
        "Update",
        "Mining",
        "Copy",
        "Not",
        "Available",
        "Users",
        "From",
        "Regions",
        "May",
        "Be",
        "Unable",
        "To",
        "Trade",
    }
)


def _extract_symbol_tokens(title: str) -> list[str]:
    """Pull ticker-like tokens from an announcement title (best-effort)."""
    tokens: list[str] = []
    for match in re.findall(r"\(([A-Z0-9]{2,12})\)", title):
        token = match.strip()
        if token and token not in tokens:
            tokens.append(token)
    if not tokens:
        for match in re.findall(r"\b[A-Z][A-Z0-9]{1,11}\b", title):
            token = match.strip()
            if token not in _ANNOUNCEMENT_TOKEN_STOP and token not in tokens:
                tokens.append(token)
    return tokens


def _article_time(article: dict[str, Any], fallback: str) -> str:
    release = article.get("releaseDate")
    if isinstance(release, (int, float)) and release > 0:
        try:
            return datetime.fromtimestamp(release / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return fallback
    return fallback


async def _announcement_signals_binance(
    previous_entries: list[dict[str, str]], fallback_dt: str
) -> list[dict[str, str]]:
    """Listing/delisting news from the Binance announcements feed.

    Listing news is emitted only for symbols not already in the snapshot
    (early warning — the ticker may not exist yet). Delisting news is emitted
    only for markets that are in the snapshot (a live market being flagged);
    the announcement token (usually the base asset, e.g. ``ETH``) is resolved
    against the snapshot entry (e.g. ``ETHUSDT``) when possible.
    """
    if os.environ.get(_ANNOUNCEMENTS_ENV, "1") == "0":
        return []
    previous_symbols = {entry["symbol"] for entry in previous_entries}
    previous_bases = {entry.get("base", "") for entry in previous_entries if entry.get("base")}
    try:
        data = await _fetch_json(_BINANCE_ANNOUNCEMENT_URL, params=_BINANCE_ANNOUNCEMENT_PARAMS)
        articles = (
            (data or {}).get("data", {}).get("articles", []) if isinstance(data, dict) else []
        )
    except Exception as exc:  # noqa: BLE001 - secondary source, never raise
        logger.warning("cex_announcement_fetch_failed", extra={"error": str(exc)[:120]})
        return []
    if not isinstance(articles, list):
        return []

    # Dedupe by resolved symbol; a delisting announcement wins over a listing one.
    by_symbol: dict[str, dict[str, str]] = {}
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "")
        lowered = title.lower()
        if "delist" in lowered:
            action = "delisting"
        elif "list" in lowered:
            action = "listing"
        else:
            continue
        detected = _article_time(article, fallback_dt)
        for token in _extract_symbol_tokens(title):
            # Resolve the announcement token against the known market set.
            if token in previous_symbols or token in previous_bases:
                if action == "listing":
                    continue  # already live — old news
                entry = next(
                    (e for e in previous_entries if e["symbol"] == token or e.get("base") == token),
                    None,
                )
                if entry:
                    symbol = entry["symbol"]
                    base = entry.get("base") or token
                    quote = entry.get("quote") or ""
                else:
                    symbol, base, quote = token, token, ""
            else:
                if action == "delisting":
                    continue  # delist news for an unknown market — stale
                symbol, base, quote = token, token, ""
            existing = by_symbol.get(symbol)
            if action == "delisting" or existing is None:
                by_symbol[symbol] = {
                    "exchange": "binance",
                    "symbol": symbol,
                    "base": base,
                    "quote": quote,
                    "action": action,
                    "detected_at_utc": detected,
                    "source": "binance_announcement",
                }

    return list(by_symbol.values())
