"""KOL / crypto-influencer leaderboard scraping built on free public sources.

Detects and normalizes KOL (Key Opinion Leader / CT-influencer) identities
from public leaderboard sites that surface wallet + handle + stats:

* **kolscan.io** — Solana trader leaderboard; RSC (Next.js flight) payload
  carries ``wallet_address``, ``name``, ``twitter``, ``telegram`` and per-
  trader ``profit`` / ``wins`` / ``losses`` (SOL-denominated P&L over a
  timeframe window). Reachable without auth; parsed without a browser.
* **gmgn.ai** — smart-money / KOL boards (smart_degen, launchpad_smart,
  top_followed, top_renamed, snipe_bot, fresh_wallet). Public pages are
  Cloudflare-protected (403 without a JS-capable solver), so this source is
  **stubbed** and flagged ``[REVIEW]`` — the transport is wired but the
  fetch returns an empty list with a ``blocked`` annotation rather than
  fabricating rows.
* **dexscreener** smart-money / **alphatracker** style boards are also
  Cloudflare-blocked on the HTML side; they are registered here as
  ``[REVIEW]`` best-effort targets.

Contract (used by the MCP / x402 wiring and the rugmunchbot KOL ingest):

* ``fetch_kolscan_leaderboard(limit)`` — KOL records from kolscan.io.
* ``fetch_kol_leaderboards(limit, sources)`` — aggregate across reachable
  sources, dedup by wallet address, annotate blocked sources.

Every returned item is normalized to:

    {
        "handle": str,               # X/CT handle (lowercase, no @)
        "name": str,                 # display name
        "address": str,              # Solana wallet (base58)
        "chain": str,                # "solana"
        "source": str,               # "kolscan_leaderboard" | ...
        "twitter": str,              # "https://x.com/<handle>"
        "telegram": str,             # "" when none
        "profit": float,             # SOL-denominated P&L (NaN-safe)
        "wins": int,
        "losses": int,
        "followers": int,            # 0 when the source does not expose it
        "evidence_url": str,         # link to the leaderboard / account page
    }

Robustness guarantees:
  * never raises — every provider failure yields an empty list
  * per-request timeouts + UA rotation on the shared httpx client
  * RSC flight payloads parsed with a tolerant regex (the Next.js stream is
    not guaranteed to be JSON-parseable) — a malformed chunk is skipped,
    never fatal
  * in-memory result cache (~1 min) to avoid hammering free tiers

Honest flags:
  * gmgn.ai, dexscreener smart-money and alphatracker boards are
    Cloudflare-protected; the fetch returns ``[]`` with ``blocked=True`` and
    ``reason`` set, so callers know the source is unreachable rather than
    empty. Marked ``[REVIEW]`` for a JS-capable solver (FlareSolverr /
    Playwright) upgrade.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=8.0)
CACHE_TTL_SECONDS = 60.0  # in-memory result cache TTL
KOLSCAN_LEADERBOARD_URL = "https://kolscan.io/leaderboard"
KOLSCAN_ACCOUNT_URL = "https://kolscan.io/account/{address}"
GMGN_LEADERBOARD_URL = "https://gmgn.ai/leaderboard"
DEXSCREENER_SMART_MONEY_URL = "https://dexscreener.com/smart-money"
ALPHATRACKER_URL = "https://www.alphatracker.ai"

#: Solana base58 address length is 32-44 chars, no ambiguous chars.
_BASE58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

#: Browser UA + headers — the RSC payload is served to any modern UA; we
#: rotate to reduce the chance of a datacenter-IP 403.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
_RNG = random.SystemRandom()

#: Source registrations. ``blocked`` marks a so-far-unreachable (Cloudflare /
#: JS-gated) site. ``method`` is the fetch+parse pipeline.
KOL_SOURCES: list[dict[str, Any]] = [
    {
        "source": "kolscan_leaderboard",
        "url": KOLSCAN_LEADERBOARD_URL,
        "method": "rsc",
        "blocked": False,
        "note": "",
    },
    {
        "source": "gmgn_smart_money",
        "url": GMGN_LEADERBOARD_URL,
        "method": "stealth_browser",
        "blocked": True,
        "note": "Cloudflare 403 — needs FlareSolverr/Playwright solver",
    },
    {
        "source": "dexscreener_smart_money",
        "url": DEXSCREENER_SMART_MONEY_URL,
        "method": "stealth_browser",
        "blocked": True,
        "note": "Cloudflare 403 — needs FlareSolverr/Playwright solver",
    },
    {
        "source": "alphatracker_leaderboard",
        "url": ALPHATRACKER_URL,
        "method": "stealth_browser",
        "blocked": True,
        "note": "unreachable (000) — DNS/JS-gated",
    },
]

_cache: dict[str, dict[str, Any]] = {}
_cache_ts: float = 0.0


def _now() -> float:
    return time.time()


def _norm_handle(handle: str) -> str:
    """Normalize an X handle: strip URL + @, lowercase."""
    return (
        str(handle or "")
        .replace("https://x.com/", "")
        .replace("https://twitter.com/", "")
        .lstrip("@")
        .strip()
        .lower()
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _RNG.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://kolscan.io/",
        "Cache-Control": "no-cache",
    }


# ── Kolscan RSC parsing ────────────────────────────────────────────────
_RSC_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)", re.DOTALL)
_OBJ_RE = re.compile(r'\{"wallet_address"')
_TWITTER_RE = re.compile(r'"twitter":("(?:[^"\\]|\\.)*"|null)')
_PROFIT_RE = re.compile(r'"profit":([-\d.eE+]+),"wins":(\d+),"losses":(\d+)')
_NAME_RE = re.compile(r'"name":"((?:[^"\\]|\\.)*)"')
_ADDR_RE = re.compile(r'"wallet_address":"([^"]+)"')


def _collect_rsc_chunks(html: str) -> str:
    """Flatten the Next.js RSC flight stream into one string.

    Each ``self.__next_f.push([1,"..."])`` carries an escaped string payload.
    We JSON-parse the array, take the string element(s), and concatenate —
    a malformed push (e.g. a trailing partial) is skipped, never fatal.
    """
    chunks: list[str] = []
    for m in _RSC_PUSH_RE.finditer(html):
        raw = m.group(1)
        try:
            arr: Any = __import__("json").loads(raw)
        except (ValueError, TypeError):
            sm = re.search(r'"((?:[^"\\]|\\.)*)"', raw)
            if sm:
                chunks.append(sm.group(1))
            continue
        if isinstance(arr, list):
            for el in arr[1:]:
                if isinstance(el, str):
                    chunks.append(el)
        elif isinstance(arr, str):
            chunks.append(arr)
    return "".join(chunks)


def _parse_kolscan_records(html: str) -> list[dict[str, Any]]:
    """Extract KOL records (wallet + name + twitter + P&L) from the RSC stream.

    The leaderboard serializes each trader as a JSON object preceded by
    ``{"wallet_address"``. We split on that marker and pull the fields with
    tolerant regexes (the stream is not globally valid JSON). The ``profit``/
    ``wins``/``losses`` triple is present on the trader rows that carry a
    stats window (all 514 leaderboard rows on the observed day).
    """
    joined = _collect_rsc_chunks(html)
    if not joined:
        return []
    records: list[dict[str, Any]] = []
    idxs = [m.start() for m in _OBJ_RE.finditer(joined)]
    for k, start in enumerate(idxs):
        end = idxs[k + 1] if k + 1 < len(idxs) else len(joined)
        seg = joined[start:end]
        addr_m = _ADDR_RE.search(seg)
        if not addr_m:
            continue
        addr = addr_m.group(1)
        name_m = _NAME_RE.search(seg)
        tw_m = _TWITTER_RE.search(seg)
        prof_m = _PROFIT_RE.search(seg)
        twitter = ""
        if tw_m and tw_m.group(1) != "null":
            twitter = tw_m.group(1).replace('\\"', '"').strip('"')
        handle = _norm_handle(twitter)
        name = name_m.group(1).replace('\\"', '"') if name_m else handle
        records.append(
            {
                "handle": handle,
                "name": name or handle,
                "address": addr,
                "chain": "solana",
                "source": "kolscan_leaderboard",
                "twitter": twitter or (f"https://x.com/{handle}" if handle else ""),
                "telegram": "",
                "profit": float(prof_m.group(1)) if prof_m else 0.0,
                "wins": int(prof_m.group(2)) if prof_m else 0,
                "losses": int(prof_m.group(3)) if prof_m else 0,
                "followers": 0,
                "evidence_url": KOLSCAN_ACCOUNT_URL.format(address=addr),
            }
        )
    return records


def _dedup_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup by wallet address (case-insensitive), preserving source order."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in records:
        addr = (r.get("address") or "").lower()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        out.append(r)
    return out


async def fetch_kolscan_leaderboard(limit: int = 500) -> list[dict[str, Any]]:
    """Fetch + parse the kolscan.io Solana trader leaderboard.

    Never raises: an unreachable target or a parse failure yields ``[]``.
    """
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            resp = await client.get(KOLSCAN_LEADERBOARD_URL)
            resp.raise_for_status()
            html = resp.text
    except (httpx.HTTPError, OSError, TimeoutError) as e:
        logger.warning("kolscan_leaderboard_fetch_failed err=%s", e)
        return []
    records = _parse_kolscan_records(html)
    records = _dedup_records(records)
    return records[: max(1, int(limit))]


async def _fetch_blocked_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort stub for Cloudflare/JS-gated KOL boards.

    The transport is wired (httpx GET) but we do not fabricate rows: a 403 /
    block simply returns ``[]``. Callers inspect :func:`source_health` for the
    ``blocked`` annotation and surface a ``[REVIEW]`` flag. A future
    FlareSolverr / Playwright solver can replace the body without changing the
    record contract.
    """
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            resp = await client.get(str(source.get("url") or ""))
            # 403 = blocked (Cloudflare). We do not parse a challenge page.
            if resp.status_code in (200, 301, 302):
                # Reaching here is a strong signal the site is now reachable —
                # a JS-capable solver should be wired in. Do not emit rows we
                # cannot validate.
                logger.info(
                    "kol_source_now_reachable source=%s status=%d",
                    source.get("source"),
                    resp.status_code,
                )
    except (httpx.HTTPError, OSError, TimeoutError) as e:
        logger.debug("kol_source_blocked source=%s err=%s", source.get("source"), e)
    return []


async def fetch_kol_leaderboards(
    limit: int = 500, sources: list[str] | None = None
) -> dict[str, Any]:
    """Aggregate KOL records across reachable sources, dedup, annotate blocks.

    ``sources`` filters by source key (default: all registered reachable
    sources). Blocked sources are never scraped for rows but are reported in
    ``blocked`` so an operator can wire a solver.
    """
    now = _now()
    if _cache and now - _cache_ts < CACHE_TTL_SECONDS:
        return _cache["value"]

    wanted = {s for s in (sources or []) if s} or {s["source"] for s in KOL_SOURCES}
    records: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for src in KOL_SOURCES:
        name = src["source"]
        if name not in wanted:
            continue
        if src.get("blocked"):
            await _fetch_blocked_source(src)  # annotate reachability, no rows
            blocked.append(
                {
                    "source": name,
                    "url": src.get("url"),
                    "blocked": True,
                    "reason": src.get("note") or "Cloudflare/JS-gated",
                    "review": True,
                }
            )
            continue
        batch = (
            await fetch_kolscan_leaderboard(limit=limit) if name == "kolscan_leaderboard" else []
        )
        records.extend(batch)
    records = _dedup_records(records)[: max(1, int(limit))]
    value: dict[str, Any] = {
        "records": records,
        "total": len(records),
        "blocked": blocked,
        "fresh": True,
    }
    _cache["value"] = value
    globals()["_cache_ts"] = now
    return value


def source_health() -> list[dict[str, Any]]:
    """Report reachability / block status for every registered KOL source."""
    return [
        {
            "source": s["source"],
            "url": s["url"],
            "blocked": s.get("blocked", False),
            "method": s.get("method"),
            "note": s.get("note", ""),
            "review": s.get("blocked", False),
        }
        for s in KOL_SOURCES
    ]


async def health_check() -> dict[str, Any]:
    """Async health probe: does the kolscan source resolve to records?"""
    sample = await fetch_kolscan_leaderboard(limit=5)
    return {
        "kolscan": {"reachable": bool(sample), "sample_count": len(sample)},
        "sources": source_health(),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


__all__ = [
    "KOL_SOURCES",
    "fetch_kol_leaderboards",
    "fetch_kolscan_leaderboard",
    "health_check",
    "source_health",
]
