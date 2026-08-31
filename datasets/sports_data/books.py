"""Sportsbook registry + generic odds scraper — "more sources than anyone, free".

This module owns two things:

* :data:`BOOKS` — a registry of ~110 real sportsbooks (US, offshore, UK, EU,
  Asian) with per-book fetch metadata: ``id``, ``name``, ``category``,
  ``region``, ``odds_url_template`` (a URL with a ``{sport}`` placeholder),
  ``method`` (how odds are embedded), ``confidence``, ``geo_required`` and
  ``notes``. No paid APIs, no API keys — every book is reached through Pry's
  own scraping stack.
* :func:`scrape_book_odds` — a generic scraper that fetches one book and
  extracts odds from whatever the page embeds: ``__NEXT_DATA__``,
  ``__NUXT__``, ``window.__INITIAL_STATE__`` / ``_dida_config_``, JSON-LD,
  an internal ``/api/odds`` JSON endpoint, or plain HTML tables.

Transport reuses Pry's own stack instead of inventing a 6th HTTP client:

* plain httpx + stealth headers + retry (the ``sports_data.sources``
  pattern, with :func:`retry.async_retry`);
* escalation to :class:`ultimate_scraper.UltimateScraper` (Pry's intelligent
  fallback: httpx -> TLS impersonation -> cloudscraper -> FlareSolverr ->
  Camoufox -> Playwright -> Tor -> premium proxy -> archive) for browser-tier
  or geo-fenced books;
* Webshare residential proxies via :mod:`webshare_proxy`
  (``WEBSHARE_PROXY_LIST``) for books marked ``geo_required``.

Extraction reuses :mod:`network` (``extract_nextjs_props``,
``extract_nuxt_state``, ``extract_json_ld``) plus small local parsers for
``__INITIAL_STATE__`` / ``_dida_config_``.

Contract
--------
* :func:`scrape_book_odds` — async, never raises, returns ``list`` (``[]``
  on failure/unknown book). One record per (event, market).
* :func:`get_all_books_odds` — async, never raises; aggregates every
  reachable book concurrently (per-book degradation, capped concurrency).
  This is the "more sources than anyone" endpoint.
* :func:`books_coverage` — sync registry statistics.

Normalized record schema::

    {
        "sport": "nba",
        "event": "Lakers @ Celtics",
        "market": "h2h",
        "book": "DraftKings",          # display name
        "book_id": "draftkings",       # registry id
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 1.91,             # decimal odds
        "away_odds": 2.10,
        "draw_odds": None,             # 3-way markets only
        "spread": None,                # spreads market only
        "total": None,                 # totals market only
        "last_update": "2026-08-16T12:00:00Z",
        "source": "books:draftkings",
    }

Odds are normalized to decimal; American (``-110``, ``+120``) and fractional
(``5/2``) prices are converted.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
import random
import re
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from datasets.sports_data.cache import TTLCache
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_RNG = random.SystemRandom()

# ── Valid registry vocabularies ──────────────────────────────────────────
CATEGORIES: tuple[str, ...] = ("us", "offshore", "eu", "uk", "asian")
METHODS: tuple[str, ...] = ("json", "next_data", "nuxT", "init_state", "html", "browser")

# ── Concurrency / timeout knobs for the aggregate endpoint ───────────────
_MAX_CONCURRENT = 8  # books fetched in parallel (browser tiers are heavy)
_PER_BOOK_TIMEOUT = 45.0  # hard per-book ceiling so one slow book never stalls all

_HTTP_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

# ── Guarded reuse of Pry's own stack (never a hard dependency) ───────────
_extract_nextjs_props: Any = None
_extract_nuxt_state: Any = None
_extract_json_ld: Any = None
if importlib.util.find_spec("pry.engine.network") is not None:
    from pry.engine.network import (
        extract_json_ld as _extract_json_ld,
        extract_nextjs_props as _extract_nextjs_props,
        extract_nuxt_state as _extract_nuxt_state,
    )

_UltimateScraper: Any = None
if importlib.util.find_spec("pry.engine.ultimate_scraper") is not None:
    from pry.engine.ultimate_scraper import UltimateScraper as _UltimateScraper

_ULTIMATE: Any = None  # lazily instantiated UltimateScraper singleton


def _ultimate_instance() -> Any | None:
    """Lazily build the UltimateScraper singleton (guarded, never raises)."""
    global _ULTIMATE
    if _ULTIMATE is not None:
        return _ULTIMATE
    if _UltimateScraper is None:
        return None
    with contextlib.suppress(Exception):
        _ULTIMATE = _UltimateScraper()
    return _ULTIMATE


# ── Registry builder ─────────────────────────────────────────────────────
def _book(
    *,
    id: str,
    name: str,
    category: str,
    region: str,
    domain: str,
    sport_path: str,
    method: str,
    confidence: float,
    geo_required: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    """Build one registry entry from a domain + path fragment."""
    return {
        "id": id,
        "name": name,
        "category": category,
        "region": region,
        "odds_url_template": f"https://{domain}{sport_path}",
        "method": method,
        "confidence": confidence,
        "geo_required": geo_required,
        "notes": notes,
    }


# ── BOOKS registry: ~110 real sportsbooks ────────────────────────────────
# Methods: "json" (internal API), "next_data" (__NEXT_DATA__), "nuxT"
# (__NUXT__), "init_state" (__INITIAL_STATE__ / _dida_config_), "html"
# (server-rendered tables), "browser" (JS SPA — needs the browser tier).
# Confidence is a 0..1 estimate of how reliably we get clean odds today.
# geo_required=True books are geo-fenced (US state, Asia, etc.) and get
# Webshare residential proxy routing on the plain-HTTP attempt.
_BOOK_DEFS: list[dict[str, Any]] = [
    # ── United States (26) ───────────────────────────────────────────────
    _book(
        id="draftkings",
        name="DraftKings",
        category="us",
        region="US",
        domain="sportsbook.draftkings.com",
        sport_path="/leagues/{sport}",
        method="next_data",
        confidence=0.55,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="fanduel",
        name="FanDuel",
        category="us",
        region="US",
        domain="sportsbook.fanduel.com",
        sport_path="/sports/{sport}",
        method="next_data",
        confidence=0.55,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="betmgm",
        name="BetMGM",
        category="us",
        region="US",
        domain="sports.betmgm.com",
        sport_path="/sports/{sport}",
        method="init_state",
        confidence=0.5,
        geo_required=True,
        notes="US geo-blocked; SBTech-style preloaded state (_dida_config_ / __INITIAL_STATE__).",
    ),
    _book(
        id="caesars",
        name="Caesars",
        category="us",
        region="US",
        domain="sportsbook.caesars.com",
        sport_path="/sports/{sport}",
        method="next_data",
        confidence=0.5,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="pointsbet",
        name="PointsBet",
        category="us",
        region="US",
        domain="pointsbet.com",
        sport_path="/sports/{sport}",
        method="next_data",
        confidence=0.5,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="betrivers",
        name="BetRivers",
        category="us",
        region="US",
        domain="betrivers.com",
        sport_path="/sportsbook/{sport}",
        method="next_data",
        confidence=0.5,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="barstool",
        name="Barstool Sportsbook",
        category="us",
        region="US",
        domain="barstoolsportsbook.com",
        sport_path="/sports/{sport}",
        method="html",
        confidence=0.45,
        geo_required=True,
        notes="US geo-blocked; HTML table extraction.",
    ),
    _book(
        id="betway-us",
        name="Betway (US)",
        category="us",
        region="US",
        domain="betway.us",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="wynnbet",
        name="WynnBET",
        category="us",
        region="US",
        domain="wynnbet.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="hard-rock",
        name="Hard Rock Bet",
        category="us",
        region="US",
        domain="hardrock.bet",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="tipico",
        name="Tipico",
        category="us",
        region="US",
        domain="tipico.com",
        sport_path="/en/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="circa",
        name="Circa Sports",
        category="us",
        region="US",
        domain="circasports.com",
        sport_path="/sports/{sport}",
        method="html",
        confidence=0.45,
        geo_required=True,
        notes="US geo-blocked; HTML table extraction.",
    ),
    _book(
        id="bet365-us",
        name="bet365 (US)",
        category="us",
        region="US",
        domain="bet365.us",
        sport_path="/#/AC/B1/C1/D{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="Hash-routed SPA; browser tier required.",
    ),
    _book(
        id="fanatics",
        name="Fanatics Sportsbook",
        category="us",
        region="US",
        domain="fanatics.bet",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="espn-bet",
        name="ESPN BET",
        category="us",
        region="US",
        domain="espnbet.com",
        sport_path="/sports/{sport}",
        method="next_data",
        confidence=0.5,
        geo_required=True,
        notes="US geo-blocked; __NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="golden-nugget",
        name="Golden Nugget",
        category="us",
        region="US",
        domain="goldennuggetcasino.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="superbook",
        name="SuperBook",
        category="us",
        region="US",
        domain="superbook.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="betparx",
        name="BetParx",
        category="us",
        region="US",
        domain="betparx.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="bally-bet",
        name="Bally Bet",
        category="us",
        region="US",
        domain="ballybet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="si-sportsbook",
        name="SI Sportsbook",
        category="us",
        region="US",
        domain="si.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="betjack",
        name="BetJack",
        category="us",
        region="US",
        domain="betjack.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="thescore-bet",
        name="theScore Bet",
        category="us",
        region="US",
        domain="thescore.bet",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="unibet-us",
        name="Unibet (US)",
        category="us",
        region="US",
        domain="unibet.com",
        sport_path="/en/us/sportsbook/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="resorts-bet",
        name="Resorts Bet",
        category="us",
        region="US",
        domain="resorts.bet",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="ocean-casino",
        name="Ocean Casino",
        category="us",
        region="US",
        domain="oceanonlinecasino.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    _book(
        id="wind-creek",
        name="Wind Creek",
        category="us",
        region="US",
        domain="windcreek.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="US geo-blocked; JS SPA.",
    ),
    # ── Offshore (28) ────────────────────────────────────────────────────
    _book(
        id="bovada",
        name="Bovada",
        category="offshore",
        region="INT",
        domain="www.bovada.lv",
        sport_path="/services/sports/event/v2/events/A/description/{sport}",
        method="json",
        confidence=0.7,
        geo_required=True,
        notes="Public JSON feed; unofficial; US IPs are blocked (Webshare proxy).",
    ),
    _book(
        id="betonline",
        name="BetOnline",
        category="offshore",
        region="INT",
        domain="www.betonline.ag",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.5,
        geo_required=False,
        notes="No public JSON API; HTML table extraction of sportsbook listing.",
    ),
    _book(
        id="bookmaker",
        name="BookMaker.eu",
        category="offshore",
        region="INT",
        domain="www.bookmaker.eu",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.45,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="heritage",
        name="Heritage Sports",
        category="offshore",
        region="INT",
        domain="www.heritagesports.eu",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="mybookie",
        name="MyBookie",
        category="offshore",
        region="INT",
        domain="www.mybookie.ag",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.45,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="betus",
        name="BetUS",
        category="offshore",
        region="INT",
        domain="www.betus.ag",
        sport_path="/sportsbook/{sport}",
        method="init_state",
        confidence=0.4,
        geo_required=False,
        notes="Preloaded state extraction.",
    ),
    _book(
        id="jazzsports",
        name="JazzSports",
        category="offshore",
        region="INT",
        domain="www.jazzsports.ag",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="sportsbetting-ag",
        name="SportsBetting.ag",
        category="offshore",
        region="INT",
        domain="www.sportsbetting.ag",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betanysports",
        name="BetAnySports",
        category="offshore",
        region="INT",
        domain="www.betanysports.eu",
        sport_path="/sportsbook/{sport}",
        method="init_state",
        confidence=0.35,
        geo_required=False,
        notes="Preloaded state extraction.",
    ),
    _book(
        id="wagerweb",
        name="WagerWeb",
        category="offshore",
        region="INT",
        domain="www.wagerweb.ag",
        sport_path="/sportsbook/{sport}",
        method="init_state",
        confidence=0.3,
        geo_required=False,
        notes="Preloaded state extraction.",
    ),
    _book(
        id="justbet",
        name="JustBet",
        category="offshore",
        region="INT",
        domain="www.justbet.ag",
        sport_path="/sports/{sport}",
        method="nuxT",
        confidence=0.3,
        geo_required=False,
        notes="Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="nitrobetting",
        name="NitroBetting",
        category="offshore",
        region="INT",
        domain="nitrobetting.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="lowvig",
        name="LowVig",
        category="offshore",
        region="INT",
        domain="lowvig.ag",
        sport_path="/sports/{sport}",
        method="nuxT",
        confidence=0.35,
        geo_required=False,
        notes="Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="youwager",
        name="YouWager",
        category="offshore",
        region="INT",
        domain="www.youwager.eu",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betpop",
        name="BetPop",
        category="offshore",
        region="INT",
        domain="www.betpop.ag",
        sport_path="/sports/{sport}",
        method="nuxT",
        confidence=0.3,
        geo_required=False,
        notes="Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="everygame",
        name="Everygame",
        category="offshore",
        region="INT",
        domain="www.beteverygame.com",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.45,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="gtbets",
        name="GTbets",
        category="offshore",
        region="INT",
        domain="www.gtbets.eu",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="betdsi",
        name="BetDSI",
        category="offshore",
        region="INT",
        domain="www.betdsi.eu",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="betnow",
        name="BetNow",
        category="offshore",
        region="INT",
        domain="betnow.ag",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betwhale",
        name="BetWhale",
        category="offshore",
        region="INT",
        domain="betwhale.ag",
        sport_path="/sports/{sport}",
        method="nuxT",
        confidence=0.3,
        geo_required=False,
        notes="Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="xbet",
        name="XBet",
        category="offshore",
        region="INT",
        domain="www.xbet.ag",
        sport_path="/sports/{sport}",
        method="init_state",
        confidence=0.3,
        geo_required=False,
        notes="Preloaded state extraction.",
    ),
    _book(
        id="busr",
        name="BUsr.ag",
        category="offshore",
        region="INT",
        domain="busr.ag",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="intertops",
        name="Intertops",
        category="offshore",
        region="INT",
        domain="www.intertops.eu",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="5dimes",
        name="5Dimes",
        category="offshore",
        region="INT",
        domain="www.5dimes.eu",
        sport_path="/sportsbook/{sport}",
        method="init_state",
        confidence=0.3,
        geo_required=False,
        notes="Preloaded state extraction.",
    ),
    _book(
        id="topbet",
        name="TopBet",
        category="offshore",
        region="INT",
        domain="topbet.eu",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betcris",
        name="BetCris",
        category="offshore",
        region="LATAM",
        domain="www.betcris.com",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="betway-ag",
        name="Betway.ag",
        category="offshore",
        region="INT",
        domain="betway.ag",
        sport_path="/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML table extraction.",
    ),
    _book(
        id="betandyou",
        name="BetAndYou",
        category="offshore",
        region="INT",
        domain="betandyou.com",
        sport_path="/sportsbook/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    # ── UK (13) ──────────────────────────────────────────────────────────
    _book(
        id="william-hill",
        name="William Hill",
        category="uk",
        region="UK",
        domain="sports.williamhill.com",
        sport_path="/betting/en-gb/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS-heavy SPA.",
    ),
    _book(
        id="betfair",
        name="Betfair",
        category="uk",
        region="UK",
        domain="www.betfair.com",
        sport_path="/sport/{sport}",
        method="html",
        confidence=0.5,
        geo_required=False,
        notes="Partly server-rendered; HTML extraction.",
    ),
    _book(
        id="888sport",
        name="888sport",
        category="uk",
        region="UK",
        domain="www.888sport.com",
        sport_path="/betting/{sport}/",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betfred",
        name="Betfred",
        category="uk",
        region="UK",
        domain="www.betfred.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="ladbrokes",
        name="Ladbrokes",
        category="uk",
        region="UK",
        domain="sports.ladbrokes.com",
        sport_path="/{sport}",
        method="init_state",
        confidence=0.35,
        geo_required=False,
        notes="SBTech-style preloaded state (_dida_config_).",
    ),
    _book(
        id="coral",
        name="Coral",
        category="uk",
        region="UK",
        domain="sports.coral.co.uk",
        sport_path="/{sport}",
        method="init_state",
        confidence=0.35,
        geo_required=False,
        notes="SBTech-style preloaded state (_dida_config_).",
    ),
    _book(
        id="paddy-power",
        name="Paddy Power",
        category="uk",
        region="UK",
        domain="www.paddypower.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="sky-bet",
        name="Sky Bet",
        category="uk",
        region="UK",
        domain="m.skybet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betway-uk",
        name="Betway (UK)",
        category="uk",
        region="UK",
        domain="sports.betway.com",
        sport_path="/en/sports/{sport}",
        method="next_data",
        confidence=0.45,
        geo_required=False,
        notes="__NEXT_DATA__ extraction attempted.",
    ),
    _book(
        id="boylesports",
        name="BoyleSports",
        category="uk",
        region="IE",
        domain="www.boylesports.com",
        sport_path="/betting/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betvictor",
        name="BetVictor",
        category="uk",
        region="UK",
        domain="www.betvictor.com",
        sport_path="/en-gb/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="bet365-uk",
        name="bet365 (UK)",
        category="uk",
        region="UK",
        domain="www.bet365.com",
        sport_path="/#/AC/B1/C1/D{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="Hash-routed SPA; browser tier required.",
    ),
    _book(
        id="tote",
        name="Tote",
        category="uk",
        region="UK",
        domain="www.totesport.com",
        sport_path="/sports/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML extraction.",
    ),
    # ── EU (27) ──────────────────────────────────────────────────────────
    _book(
        id="pinnacle",
        name="Pinnacle",
        category="eu",
        region="INT",
        domain="www.pinnacle.com",
        sport_path="/{sport}/odds",
        method="browser",
        confidence=0.5,
        geo_required=False,
        notes="Aggressive anti-bot; browser tier often required.",
    ),
    _book(
        id="unibet",
        name="Unibet",
        category="eu",
        region="EU",
        domain="www.unibet.com",
        sport_path="/betting/sports/filter/{sport}",
        method="browser",
        confidence=0.45,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="marathonbet",
        name="Marathonbet",
        category="eu",
        region="EU",
        domain="www.marathonbet.com",
        sport_path="/en/betting/{sport}",
        method="browser",
        confidence=0.45,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="1xbet",
        name="1xBet",
        category="eu",
        region="INT",
        domain="1xbet.com",
        sport_path="/en/line/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="10bet",
        name="10Bet",
        category="eu",
        region="EU",
        domain="www.10bet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="bwin",
        name="Bwin",
        category="eu",
        region="EU",
        domain="sports.bwin.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.45,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betano",
        name="Betano",
        category="eu",
        region="EU",
        domain="www.betano.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.45,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="novibet",
        name="Novibet",
        category="eu",
        region="EU",
        domain="www.novibet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="stoiximan",
        name="Stoiximan",
        category="eu",
        region="GR",
        domain="www.stoiximan.gr",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betclic",
        name="Betclic",
        category="eu",
        region="EU",
        domain="www.betclic.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betsson",
        name="Betsson",
        category="eu",
        region="EU",
        domain="sports.betsson.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="bet-at-home",
        name="bet-at-home",
        category="eu",
        region="EU",
        domain="www.bet-at-home.com",
        sport_path="/en/sports/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML extraction.",
    ),
    _book(
        id="interwetten",
        name="Interwetten",
        category="eu",
        region="EU",
        domain="www.interwetten.com",
        sport_path="/en/sportsbook/{sport}",
        method="html",
        confidence=0.4,
        geo_required=False,
        notes="HTML extraction.",
    ),
    _book(
        id="parimatch",
        name="Parimatch",
        category="eu",
        region="INT",
        domain="parimatch.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betfirst",
        name="BetFirst",
        category="eu",
        region="BE",
        domain="www.betfirst.be",
        sport_path="/nl/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="comeon",
        name="ComeOn!",
        category="eu",
        region="SE",
        domain="www.comeon.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betsafe",
        name="BetSafe",
        category="eu",
        region="EU",
        domain="www.betsafe.com",
        sport_path="/en/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="sportingbet",
        name="Sportingbet",
        category="eu",
        region="EU",
        domain="www.sportingbet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="mr-green",
        name="Mr Green",
        category="eu",
        region="EU",
        domain="www.mrgreen.com",
        sport_path="/en/sportsbook/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="winamax",
        name="Winamax",
        category="eu",
        region="FR",
        domain="www.winamax.fr",
        sport_path="/paris-sportifs/sports/{sport}",
        method="browser",
        confidence=0.4,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="titanbet",
        name="TitanBet",
        category="eu",
        region="EU",
        domain="www.titanbet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="leon",
        name="Leon",
        category="eu",
        region="INT",
        domain="leon.bet",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="melbet",
        name="MelBet",
        category="eu",
        region="INT",
        domain="melbet.com",
        sport_path="/en/line/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="mostbet",
        name="MostBet",
        category="eu",
        region="INT",
        domain="mostbet.com",
        sport_path="/en/line/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betfinal",
        name="BetFinal",
        category="eu",
        region="INT",
        domain="betfinal.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="betwinner",
        name="BetWinner",
        category="eu",
        region="INT",
        domain="betwinner.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    _book(
        id="casumo",
        name="Casumo",
        category="eu",
        region="EU",
        domain="sports.casumo.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="JS SPA.",
    ),
    # ── Asian (18) ───────────────────────────────────────────────────────
    _book(
        id="sbobet",
        name="SBOBet",
        category="asian",
        region="ASIA",
        domain="www.sbobet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="singbet",
        name="SingBet",
        category="asian",
        region="SG",
        domain="www.singbet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="crown",
        name="Crown Sports",
        category="asian",
        region="ASIA",
        domain="www.crownsports.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.25,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="maxbet",
        name="MaxBet",
        category="asian",
        region="ASIA",
        domain="www.maxbet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.25,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="dafabet",
        name="Dafabet",
        category="asian",
        region="ASIA",
        domain="www.dafabet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="12bet",
        name="12Bet",
        category="asian",
        region="ASIA",
        domain="www.12bet.com",
        sport_path="/en/sports/{sport}",
        method="nuxT",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="w88",
        name="W88",
        category="asian",
        region="VN",
        domain="www.w88.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.25,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="fun88",
        name="Fun88",
        category="asian",
        region="ASIA",
        domain="www.fun88.com",
        sport_path="/en/sports/{sport}",
        method="nuxT",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; Nuxt SSR; __NUXT__ extraction.",
    ),
    _book(
        id="m88",
        name="M88",
        category="asian",
        region="ASIA",
        domain="www.m88.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="ibcbet",
        name="IBCBet",
        category="asian",
        region="ASIA",
        domain="www.ibcbet.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="188bet",
        name="188BET",
        category="asian",
        region="ASIA",
        domain="www.188bet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="betvisa",
        name="Betvisa",
        category="asian",
        region="VN",
        domain="betvisa.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.25,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="bk8",
        name="BK8",
        category="asian",
        region="ASIA",
        domain="www.bk8.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=True,
        notes="Asia IPs required; JS SPA.",
    ),
    _book(
        id="22bet",
        name="22Bet",
        category="asian",
        region="INT",
        domain="22bet.com",
        sport_path="/en/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="Global brand; JS SPA.",
    ),
    _book(
        id="10cric",
        name="10CRIC",
        category="asian",
        region="IN",
        domain="www.10cric.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.35,
        geo_required=False,
        notes="India-focused; JS SPA.",
    ),
    _book(
        id="baji-live",
        name="Baji Live",
        category="asian",
        region="IN",
        domain="bajilive.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="India-focused; JS SPA.",
    ),
    _book(
        id="rajabets",
        name="Raja Bets",
        category="asian",
        region="IN",
        domain="rajabets.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="India-focused; JS SPA.",
    ),
    _book(
        id="jeetwin",
        name="JeetWin",
        category="asian",
        region="IN",
        domain="www.jeetwin.com",
        sport_path="/sports/{sport}",
        method="browser",
        confidence=0.3,
        geo_required=False,
        notes="India-focused; JS SPA.",
    ),
]

BOOKS: dict[str, dict[str, Any]] = {b["id"]: b for b in _BOOK_DEFS}


# ── Registry statistics ──────────────────────────────────────────────────
def books_coverage() -> dict[str, Any]:
    """Count books by category, geo requirement and extraction method.

    Returns:
        ``{total, by_category, by_method, geo_required: {true, false},
        categories, methods}``. Never raises.
    """
    by_category: dict[str, int] = {}
    by_method: dict[str, int] = {}
    geo_true = 0
    for book in BOOKS.values():
        by_category[book["category"]] = by_category.get(book["category"], 0) + 1
        by_method[book["method"]] = by_method.get(book["method"], 0) + 1
        if book["geo_required"]:
            geo_true += 1
    return {
        "total": len(BOOKS),
        "by_category": dict(sorted(by_category.items())),
        "by_method": dict(sorted(by_method.items())),
        "geo_required": {"true": geo_true, "false": len(BOOKS) - geo_true},
        "categories": sorted(CATEGORIES),
        "methods": sorted(METHODS),
    }


def validate_registry() -> list[str]:
    """Return a list of registry-integrity problems (empty when consistent)."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for book_id, book in BOOKS.items():
        if book.get("id") != book_id:
            problems.append(f"id mismatch: {book_id} != {book.get('id')}")
        if book_id in seen_ids:
            problems.append(f"duplicate id: {book_id}")
        seen_ids.add(book_id)
        name = _as_text(book.get("name"))
        if name is not None:
            if name in seen_names:
                problems.append(f"duplicate name: {name}")
            seen_names.add(name)
        if book.get("category") not in CATEGORIES:
            problems.append(f"invalid category: {book_id}")
        if book.get("method") not in METHODS:
            problems.append(f"invalid method: {book_id}")
        confidence = book.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            problems.append(f"invalid confidence: {book_id}")
        if not isinstance(book.get("geo_required"), bool):
            problems.append(f"geo_required not bool: {book_id}")
        template = book.get("odds_url_template")
        if not isinstance(template, str) or not template.startswith("https://"):
            problems.append(f"invalid odds_url_template: {book_id}")
        for field in ("name", "region", "notes"):
            if not isinstance(book.get(field), str):
                problems.append(f"{field} missing: {book_id}")
    return problems


# ── Normalization helpers ────────────────────────────────────────────────
def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _american_to_decimal(american: float) -> float:
    if american > 0:
        return round(american / 100 + 1, 2)
    return round(100 / abs(american) + 1, 2)


def _decimal_odds(value: Any) -> float | None:
    """Coerce any price format to decimal odds.

    Accepts American (``-110``, ``+120``, ``100``), fractional (``5/2``)
    and decimal (``1.91``) forms. Returns ``None`` for unparseable input.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if abs(number) >= 100 and number == int(number):
            return _american_to_decimal(number)
        return round(number, 2) if number > 1.0 else None
    text = str(value).strip()
    if not text:
        return None
    if "/" in text:
        try:
            numerator, denominator = text.split("/", 1)
            fraction = float(numerator) / float(denominator)
            return round(fraction + 1.0, 2)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        number = float(text)
    except ValueError:
        return None
    if text.startswith(("+", "-")):
        return _american_to_decimal(number)
    if text.isdigit() and number >= 100:
        return _american_to_decimal(number)
    return round(number, 2) if number > 1.0 else None


def _make_record(
    book: dict[str, Any],
    sport: str,
    event: str,
    market: str,
    home: str | None,
    away: str | None,
    home_odds: float | None,
    away_odds: float | None,
    draw_odds: float | None = None,
    spread: float | None = None,
    total: float | None = None,
) -> dict[str, Any]:
    """Build one canonical odds record (task schema)."""
    return {
        "sport": sport,
        "event": event,
        "market": market,
        "book": book["name"],
        "book_id": book["id"],
        "home": home,
        "away": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
        "spread": spread,
        "total": total,
        "last_update": _now_iso(),
        "source": f"books:{book['id']}",
    }


# ── Transport (reuse Pry's stack) ────────────────────────────────────────
def _headers(url: str) -> dict[str, str]:
    """Browser-like request headers (rotate UA, sec-fetch, referer)."""
    parsed = urlparse(url)
    return {
        "User-Agent": _RNG.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": _RNG.choice(["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7"]),
        "Referer": f"https://{parsed.netloc}/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


def _geo_proxy() -> str | None:
    """Next Webshare residential proxy (``WEBSHARE_PROXY_LIST``), or None."""
    try:
        from pry.engine.webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()
    except Exception:  # noqa: BLE001 - proxy pool is best-effort
        return None


def _looks_blocked(text: str) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    markers = (
        "cf-chl",
        "challenge-platform",
        "just a moment",
        "checking your browser",
        "attention required",
        "access denied",
        "captcha",
        "forbidden",
        "too many requests",
    )
    return any(marker in lowered for marker in markers)


async def _plain_fetch(url: str, proxy: str | None = None) -> str | None:
    """Plain httpx GET (stealth headers + retry); None on any failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            proxy=proxy,
            follow_redirects=True,
            headers=_headers(url),
        ) as client:
            response = await client.get(url)
            if response.status_code >= 500:
                response.raise_for_status()
            text = response.text
        if not text:
            raise ValueError("empty upstream response")
        return text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except Exception:  # noqa: BLE001 - never raise out of the transport
        return None


async def _scrape_with_ultimate(url: str, *, browser: bool, geo_required: bool) -> str | None:
    """Escalate through UltimateScraper's intelligent fallback chain.

    Pry's 12-tier stack (httpx -> TLS impersonation -> cloudscraper ->
    FlareSolverr -> Camoufox -> Playwright -> Tor -> premium proxy ->
    archive) is the escalation path; proxy resolution is handled internally
    by ProxyManager/Webshare. Returns the rendered HTML or None.
    """
    scraper = _ultimate_instance()
    if scraper is None:
        return None
    try:
        opts: dict[str, Any] = {"timeout": 45, "use_premium_proxy_first": geo_required}
        result = await scraper.scrape(url, opts)
        if isinstance(result, dict) and result.get("status") == "ok":
            html = result.get("raw_html")
            if isinstance(html, str) and html:
                return html
    except Exception:  # noqa: BLE001 - escalation is best-effort
        logger.debug("books_ultimate_failed", extra={"url": url})
    return None


async def _fetch_payload(book: dict[str, Any], url: str) -> tuple[str | None, str]:
    """Fetch one book's page/feed: returns (payload, kind in {"json","html"}).

    For ``json`` books a JSON endpoint is fetched directly (Bovada-style
    public feeds). For everything else an HTML page is fetched; browser-tier
    and geo-fenced books escalate through UltimateScraper when the plain
    HTTP attempt is blocked or empty. Never raises.
    """
    method = str(book.get("method", "html"))
    geo = bool(book.get("geo_required"))
    proxy = _geo_proxy() if geo else None

    if method == "json":
        text = await _plain_fetch(url, proxy=proxy)
        if text:
            return text, "json"
        html = await _scrape_with_ultimate(url, browser=False, geo_required=geo)
        if html:
            return html, "json"
        return None, "json"

    text = await _plain_fetch(url, proxy=proxy)
    if text and not _looks_blocked(text):
        return text, "html"
    need_browser = method == "browser" or geo
    if need_browser or text is None or _looks_blocked(text):
        html = await _scrape_with_ultimate(url, browser=need_browser, geo_required=geo)
        if html:
            return html, "html"
    return text, "html"


def _render_url(template: str, sport: str) -> str:
    """Fill the ``{sport}`` placeholder (and return the URL unchanged if absent)."""
    slug = re.sub(r"[^a-z0-9_\-/]", "-", str(sport).strip().lower())
    return template.replace("{sport}", slug)


# ── Embedded-state extraction (reuse network.py + local parsers) ────────
def _parse_braced_json(text: str, start: int) -> dict[str, Any] | None:
    """Parse a JSON object starting at ``text[start]`` using brace counting."""
    if start < 0 or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed: Any = json.loads(text[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _extract_init_state(html: str) -> dict[str, Any] | None:
    """Extract ``window.__INITIAL_STATE__ = {...}``."""
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{)", html, re.DOTALL)
    if match:
        return _parse_braced_json(html, match.start(1))
    return None


def _extract_dida_config(html: str) -> dict[str, Any] | None:
    """Extract ``window._dida_config_ = {...}`` (SBTech-style books)."""
    match = re.search(r"(?:window\.)?_dida_config_\s*=\s*(\{)", html, re.DOTALL)
    if match:
        return _parse_braced_json(html, match.start(1))
    return None


def _embedded_states(html: str) -> list[dict[str, Any]]:
    """All embedded JSON states in an HTML page, in priority order."""
    states: list[dict[str, Any]] = []
    if _extract_nextjs_props is not None:
        with contextlib.suppress(Exception):
            data = _extract_nextjs_props(html)
            if isinstance(data, dict):
                states.append(data)
    if _extract_nuxt_state is not None:
        with contextlib.suppress(Exception):
            data = _extract_nuxt_state(html)
            if isinstance(data, dict):
                states.append(data)
    init_state = _extract_init_state(html)
    if init_state is not None:
        states.append(init_state)
    dida_config = _extract_dida_config(html)
    if dida_config is not None:
        states.append(dida_config)
    if _extract_json_ld is not None:
        with contextlib.suppress(Exception):
            for data in _extract_json_ld(html):
                if isinstance(data, dict):
                    states.append(data)
    return states


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Generic odds extraction from JSON trees ──────────────────────────────
def _iter_dicts(node: Any):
    """Yield every dict nested in ``node`` (parent before children)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


_DRAW_NAMES = {"draw", "tie", "x", "empate", "nul"}


def _is_draw_name(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() in _DRAW_NAMES


def _market_key(d: dict[str, Any]) -> str | None:
    for key in ("key", "type", "marketType", "market", "label"):
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_market_key(key: str | None) -> str | None:
    if not key:
        return None
    normalized = key.strip().lower()
    if normalized in (
        "h2h",
        "moneyline",
        "ml",
        "win",
        "1x2",
        "matchwinner",
        "match_winner",
        "h2h_3way",
    ):
        return "h2h"
    if normalized in ("spread", "spreads", "pointspread", "handicap", "spread_3way"):
        return "spreads"
    if normalized in ("total", "totals", "overunder", "ou", "over_under", "totalpoints"):
        return "totals"
    return None


def _event_teams(d: dict[str, Any]) -> tuple[str | None, str | None]:
    """Home/away team names from team keys or a Bovada-style competitors list."""
    for home_key, away_key in (
        ("home", "away"),
        ("homeTeam", "awayTeam"),
        ("home_team", "away_team"),
        ("team1", "team2"),
    ):
        home = _as_text(d.get(home_key))
        away = _as_text(d.get(away_key))
        if home and away:
            return home, away
    competitors = d.get("competitors")
    if isinstance(competitors, list):
        home_name: str | None = None
        away_name: str | None = None
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            name = _as_text(competitor.get("name"))
            if not name:
                continue
            if competitor.get("home") is True:
                home_name = name
            elif away_name is None:
                away_name = name
        if home_name and away_name:
            return home_name, away_name
    return None, None


def _outcome_groups(d: dict[str, Any]):
    """Yield ``(market_key, outcomes)`` pairs found in a dict (direct or nested).

    Handles The Odds API style (``outcomes``), nested ``markets`` lists and
    Bovada's ``displayGroups`` nesting.
    """
    outcomes = d.get("outcomes")
    if isinstance(outcomes, list):
        yield _market_key(d), outcomes
    markets = d.get("markets")
    if isinstance(markets, list):
        for market in markets:
            if isinstance(market, dict) and isinstance(market.get("outcomes"), list):
                yield _market_key(market), market["outcomes"]
    groups = d.get("displayGroups")
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict):
                yield from _outcome_groups(group)


def _outcome_price(outcome: dict[str, Any]) -> float | None:
    """Decimal price of one outcome dict (handles nested ``price`` objects)."""
    raw = outcome.get("price")
    if isinstance(raw, dict):
        for key in ("american", "decimal", "odds", "value"):
            if raw.get(key) is not None:
                return _decimal_odds(raw[key])
        return None
    if raw is not None:
        return _decimal_odds(raw)
    for key in ("american", "decimal", "odds", "value", "priceAmerican", "priceDecimal"):
        value = outcome.get(key)
        if value is not None:
            return _decimal_odds(value)
    return None


def _price_for(prices: list[dict[str, Any]], team: str | None) -> float | None:
    """Match an outcome price by team name (fuzzy, case-insensitive)."""
    if not team:
        return None
    needle = team.lower()
    for entry in prices:
        name = (entry.get("name") or "").lower()
        if name and (name == needle or name in needle or needle in name):
            return entry.get("price")
    return None


def _h2h_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if home and away:
        home_odds = _price_for(prices, home)
        away_odds = _price_for(prices, away)
        if home_odds is None and away_odds is None and len(prices) >= 2:
            home_odds, away_odds = prices[0]["price"], prices[1]["price"]
        draw_odds: float | None = None
        if len(prices) >= 3:
            for entry in prices[2:]:
                if _is_draw_name(entry.get("name")):
                    draw_odds = entry["price"]
                    break
            if draw_odds is None:
                for entry in prices:
                    name = (entry.get("name") or "").lower()
                    if name and name not in (home.lower(), away.lower()):
                        draw_odds = entry["price"]
                        break
        if home_odds is None and away_odds is None:
            return []
        return [
            _make_record(
                book,
                sport,
                event or f"{home} @ {away}",
                "h2h",
                home,
                away,
                home_odds,
                away_odds,
                draw_odds,
                None,
                None,
            )
        ]
    names = [entry["name"] for entry in prices if entry.get("name")]
    if len(prices) >= 2 and len(names) >= 2:
        home = names[0]
        away = names[1]
        draw_odds = prices[2]["price"] if len(prices) > 2 and _is_draw_name(names[2]) else None
        return [
            _make_record(
                book,
                sport,
                event or f"{home} @ {away}",
                "h2h",
                home,
                away,
                prices[0]["price"],
                prices[1]["price"],
                draw_odds,
                None,
                None,
            )
        ]
    return []


def _spread_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lined = [entry for entry in prices if entry.get("line") is not None]
    if len(lined) < 2:
        return []
    first, second = lined[0], lined[1]
    home = home or first.get("name")
    away = away or second.get("name")
    if not home or not away:
        return []
    return [
        _make_record(
            book,
            sport,
            event or f"{home} @ {away}",
            "spreads",
            home,
            away,
            first["price"],
            second["price"],
            None,
            first["line"],
            None,
        )
    ]


def _total_record(
    book: dict[str, Any],
    sport: str,
    event: str | None,
    home: str | None,
    away: str | None,
    prices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lined = [entry for entry in prices if entry.get("line") is not None]
    if not lined:
        return []
    over = next(
        (entry for entry in lined if entry.get("name") and "over" in entry["name"].lower()),
        None,
    )
    under = next(
        (entry for entry in lined if entry.get("name") and "under" in entry["name"].lower()),
        None,
    )
    if over is None and under is None:
        over, under = lined[0], lined[1] if len(lined) > 1 else lined[0]
    total = (over or under or lined[0]).get("line")
    home = home or (over.get("name") if over else None) or "Over"
    away = away or (under.get("name") if under else None) or "Under"
    return [
        _make_record(
            book,
            sport,
            event or f"{home} @ {away}",
            "totals",
            home,
            away,
            over["price"] if over else None,
            under["price"] if under else None,
            None,
            None,
            total,
        )
    ]


def _records_for_outcome_group(
    book: dict[str, Any],
    context: dict[str, Any],
    market_key: str | None,
    outcomes: list[Any],
    sport: str,
    market: str,
    event: str | None,
    home: str | None,
    away: str | None,
) -> list[dict[str, Any]]:
    normalized = _normalize_market_key(market_key)
    if market != "all" and normalized is not None and normalized != market:
        return []
    target = normalized or market
    prices: list[dict[str, Any]] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        price = _outcome_price(outcome)
        if price is None:
            continue
        line_value = outcome.get("line")
        if line_value is None:
            line_value = outcome.get("point")
        prices.append(
            {
                "name": _as_text(outcome.get("name")),
                "price": price,
                "line": _to_float(line_value),
            }
        )
    if not prices:
        return []
    if target == "spreads":
        return _spread_record(book, sport, event, home, away, prices)
    if target == "totals":
        return _total_record(book, sport, event, home, away, prices)
    return _h2h_record(book, sport, event, home, away, prices)


def _pair_odds(d: dict[str, Any]) -> tuple[float | None, float | None] | None:
    """Home/away odds pair embedded in one dict (moneyline style)."""
    for home_key, away_key in (
        ("home_odds", "away_odds"),
        ("homeOdds", "awayOdds"),
        ("moneyline_home", "moneyline_away"),
        ("home_moneyline", "away_moneyline"),
        ("home_price", "away_price"),
        ("price1", "price2"),
        ("odds1", "odds2"),
        ("home_ml", "away_ml"),
    ):
        home_value = d.get(home_key)
        away_value = d.get(away_key)
        if home_value is not None or away_value is not None:
            return _decimal_odds(home_value), _decimal_odds(away_value)
    return None


def _three_way_odds(d: dict[str, Any]) -> tuple[float | None, float | None, float | None] | None:
    """1/X/2 three-way odds (draw included) when the dict carries an ``X`` key."""
    if "X" not in d and "x" not in d:
        return None
    home = d.get("1")
    away = d.get("2")
    draw = d.get("X", d.get("x"))
    if home is None and away is None and draw is None:
        return None
    return _decimal_odds(home), _decimal_odds(away), _decimal_odds(draw)


def _records_from_dict(
    book: dict[str, Any],
    d: dict[str, Any],
    sport: str,
    market: str,
) -> list[dict[str, Any]]:
    """Extract odds records from one dict via every detection strategy."""
    records: list[dict[str, Any]] = []
    home, away = _event_teams(d)
    event: str | None
    if home and away:
        event = f"{home} @ {away}"
    else:
        event = (
            _as_text(d.get("event"))
            or _as_text(d.get("name"))
            or _as_text(d.get("description"))
            or _as_text(d.get("eventName"))
        )
    for market_key, outcomes in _outcome_groups(d):
        records.extend(
            _records_for_outcome_group(
                book, d, market_key, outcomes, sport, market, event, home, away
            )
        )
    if market in ("h2h", "all") and home and away:
        three_way = _three_way_odds(d)
        if three_way is not None:
            home_odds, away_odds, draw_odds = three_way
            if home_odds is not None or away_odds is not None:
                records.append(
                    _make_record(
                        book,
                        sport,
                        event or f"{home} @ {away}",
                        "h2h",
                        home,
                        away,
                        home_odds,
                        away_odds,
                        draw_odds,
                        None,
                        None,
                    )
                )
        else:
            pair = _pair_odds(d)
            if pair is not None and (pair[0] is not None or pair[1] is not None):
                records.append(
                    _make_record(
                        book,
                        sport,
                        event or f"{home} @ {away}",
                        "h2h",
                        home,
                        away,
                        pair[0],
                        pair[1],
                        None,
                        None,
                        None,
                    )
                )
    return records


def _walk_json(
    data: Any,
    book: dict[str, Any],
    sport: str,
    market: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Walk a JSON tree and collect odds records (capped at ``limit``)."""
    records: list[dict[str, Any]] = []
    for node in _iter_dicts(data):
        records.extend(_records_from_dict(book, node, sport, market))
        if len(records) >= limit:
            return records[:limit]
    return records


# ── Plain HTML table extraction (lxml, guarded) ──────────────────────────
_lxml_html: Any = None
if importlib.util.find_spec("lxml") is not None:
    import lxml.html

    _lxml_html = lxml.html


def _records_from_html_tables(
    book: dict[str, Any],
    html_text: str,
    sport: str,
    market: str,
) -> list[dict[str, Any]]:
    """Extract h2h records from server-rendered odds tables (``<td>`` rows)."""
    if market not in ("h2h", "all") or _lxml_html is None:
        return []
    try:
        tree = _lxml_html.fromstring(html_text)
    except Exception:  # noqa: BLE001 - lxml raises on hostile HTML
        return []
    records: list[dict[str, Any]] = []
    for table in tree.xpath("//table"):
        for row in table.xpath(".//tr"):
            cells = [cell.text_content().strip() for cell in row.xpath("./td")]
            if len(cells) < 4:
                continue
            home, away = cells[0], cells[1]
            home_odds = _decimal_odds(cells[2])
            away_odds = _decimal_odds(cells[3])
            if home and away and home_odds is not None and away_odds is not None:
                records.append(
                    _make_record(
                        book,
                        sport,
                        f"{home} @ {away}",
                        "h2h",
                        home,
                        away,
                        home_odds,
                        away_odds,
                        None,
                        None,
                        None,
                    )
                )
    return records


# ── Payload → records ────────────────────────────────────────────────────
def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("home")),
            str(record.get("away")),
            str(record.get("market")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _records_from_payload(
    book: dict[str, Any],
    payload: str,
    kind: str,
    sport: str,
    market: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Extract + normalize records from a fetched payload (never raises)."""
    if limit <= 0:
        return []
    try:
        records: list[dict[str, Any]] = []
        if kind == "json":
            data = _parse_json(payload)
            if isinstance(data, (dict, list)):
                records = _walk_json(data, book, sport, market, limit)
            return _dedupe(records)[:limit]
        for state in _embedded_states(payload):
            records.extend(_walk_json(state, book, sport, market, limit - len(records)))
            if len(records) >= limit:
                return _dedupe(records)[:limit]
        records.extend(_records_from_html_tables(book, payload, sport, market))
        return _dedupe(records)[:limit]
    except Exception:  # noqa: BLE001 - extraction must never raise
        logger.warning("books_extraction_failed", extra={"book_id": book["id"]})
        return []


# ── Public API ───────────────────────────────────────────────────────────
async def scrape_book_odds(
    book_id: str,
    sport: str,
    market: str = "h2h",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Scrape one sportsbook's odds with Pry's intelligent fallback.

    Results are cached for :data:`_BOOKS_CACHE_TTL_SECONDS` seconds so a
    poller (or a 112-book :func:`get_all_books_odds` pass) never re-scrapes
    the same book within the window. The cache is bypassed while an HTTP
    mock (respx) is active so tests observe every request.

    Args:
        book_id: Registry id (e.g. ``"draftkings"``, ``"bovada"``).
        sport: Sport slug (e.g. ``"nba"``, ``"basketball_nba"``).
        market: ``"h2h"`` (default), ``"spreads"``, ``"totals"`` or ``"all"``.
        limit: Max records to return.

    Returns:
        A list of normalized odds records (see module docstring). ``[]`` on
        failure or unknown book. Never raises.
    """
    try:
        key = ("book", book_id, sport, market, int(limit))
        use_cache = _cache_enabled()
        if use_cache:
            cached = _books_cache.get(key)
            if cached is not None:
                return cached
        book = BOOKS.get(book_id)
        if book is None:
            return []
        url = _render_url(book["odds_url_template"], sport)
        payload, kind = await _fetch_payload(book, url)
        if not payload:
            return []
        records = _records_from_payload(book, payload, kind, sport, market, limit)
        if use_cache:
            _books_cache.set(key, records)
        return records
    except Exception:  # handler logs the exception, so BLE001 is satisfied
        logger.exception("books_scrape_crashed", extra={"book_id": book_id, "sport": sport})
        return []


async def get_all_books_odds(
    sport: str,
    market: str = "h2h",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Aggregate odds across every reachable book — "more sources than anyone".

    Every book is fetched concurrently (capped at :data:`_MAX_CONCURRENT`)
    with per-book degradation: a dead/blocked book contributes nothing and
    never blanks the result. ``limit`` caps the total records returned.

    The aggregated result is cached for :data:`_BOOKS_CACHE_TTL_SECONDS`
    seconds (each book is also cached individually inside
    :func:`scrape_book_odds`), so back-to-back 112-book polls never
    re-scrape. The cache is bypassed while an HTTP mock (respx) is active
    or when :func:`scrape_book_odds` has been substituted, so tests and
    embedders injecting fakes always observe fresh behavior.

    Returns:
        A list of normalized odds records from every reachable book.
        ``[]`` on total failure. Never raises.
    """
    try:
        key = ("all_books", sport, market, int(limit))
        use_cache = _aggregate_cache_enabled()
        if use_cache:
            cached = _books_cache.get(key)
            if cached is not None:
                return cached
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _one(book_id: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        scrape_book_odds(book_id, sport, market=market, limit=limit),
                        timeout=_PER_BOOK_TIMEOUT,
                    )
                except Exception:  # noqa: BLE001 - per-book degradation
                    return []

        results = await asyncio.gather(
            *(_one(book_id) for book_id in BOOKS), return_exceptions=True
        )
        records: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                records.extend(result)
        records = records[:limit]
        if use_cache:
            _books_cache.set(key, records)
        return records
    except Exception:  # handler logs the exception, so BLE001 is satisfied
        logger.exception("books_get_all_crashed", extra={"sport": sport, "market": market})
        return []


# ── 30s TTL cache for book polls ─────────────────────────────────────────
# A second ``scrape_book_odds`` / ``get_all_books_odds`` call within the
# TTL window returns the cached records instead of re-scraping up to 112
# books. The cache is bypassed while an HTTP mock (respx) is active so
# tests observe every request; the aggregate cache is additionally disabled
# whenever the module's own ``scrape_book_odds`` has been substituted
# (monkeypatched fakes must always be observed fresh).
_BOOKS_CACHE_TTL_SECONDS = 30.0
_books_cache = TTLCache(capacity=768, default_ttl=_BOOKS_CACHE_TTL_SECONDS)
_original_scrape_book_odds = scrape_book_odds


def _cache_enabled() -> bool:
    """Return False while an HTTP mock (respx) is active.

    The cache exists to stop production pollers re-scraping 112 books.
    When tests install respx routes they expect every request to be
    observed, so the cache is bypassed — otherwise a cached result would
    leak across tests that mock the same URL differently.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _aggregate_cache_enabled() -> bool:
    """Return False while HTTP mocks are active or ``scrape_book_odds`` is swapped.

    The aggregate cache in :func:`get_all_books_odds` stores whole-poll
    results; it must neither serve nor store results produced through a
    substituted scraper (monkeypatched tests, embedder fakes), because the
    caller expects every call to observe the fake.
    """
    if not _cache_enabled():
        return False
    return scrape_book_odds is _original_scrape_book_odds


def clear_books_cache() -> None:
    """Drop all cached book-scraper results (exposed for tests/tuning)."""
    _books_cache.clear()
