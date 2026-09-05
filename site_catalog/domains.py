"""Pry — site catalog static data (thin loader).

The single source of truth for "how we scrape each site" lives in
``domains.json`` next to this module: one typed entry per target site that
records the scrape method, expected confidence, anti-bot posture, robots
posture, latency budget, and output schema BEFORE any tool is invoked.
Consumers (routers, MCP tools, the executor) look this up up-front so they
can pick a method and set expectations instead of guessing at scrape time.

Entries are grounded in the actual modules under ``crypto_market/``,
``marketplace/``, ``legal_docs/``, ``real_estate/``, ``jobs/``, ``travel/``,
``attention/``, ``local_data/``, ``gov_data/`` and ``ip_data/`` — the
``method`` value reflects the transport+parse technique each module really
uses. The ``document`` and ``browser`` data domains are capability entries
backed by ``pdf_extractor.py``, ``ocr_extractor.py``, ``stealth_engine.py``,
``camoufox_integration.py``, ``tor_fallback.py`` and ``proxy_manager.py``.

Entry keys (typed, validated by ``site_catalog.registry.SiteCatalog``):

* ``site_id``              — stable unique identifier
* ``domain``               — host (optionally with path prefix) the entry covers
* ``fallback_chain``       — ordered list of other ``site_id``s to try when this
                              site fails (empty list = no known fallback)
* ``tested``               — True only when the source was verified via the
                              repo's live-verified notes; False = untested
* ``method``               — Pry method vocabulary token, or ``+``-joined
                              compound (e.g. ``"stealth+next_data"``)
* ``confidence``           — 0.0-1.0 expected success probability
* ``anti_bot``             — "none" | "low" | "medium" | "high"
* ``robots``               — "allowed" | "restricted" | "unknown"
* ``latency_ms_estimate``  — median end-to-end latency budget in ms
* ``output_schema``        — normalized output key names
* ``requires_key``         — True when an API key / token is required
* ``data_domain``          — one of the 12 supported data domains

Optional keys (subset of entries):

* ``blocked``              — True when the site is currently registered as
                              blocked (e.g. Cloudflare 403)
* ``note``                 — free-form note explaining the blocked state

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Method vocabulary used across Pry (see METHOD_VOCABULARY in registry.py):
#   api, direct, next_data, embedded_json, stealth, browser, tor, proxy, signed

_DATA_FILE = Path(__file__).with_name("domains.json")


def _load_catalog() -> list[dict[str, Any]]:
    """Load the static catalog entries from ``domains.json``."""
    with _DATA_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


CATALOG: list[dict[str, Any]] = _load_catalog()

__all__ = ["CATALOG"]
