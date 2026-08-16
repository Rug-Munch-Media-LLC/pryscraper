"""Pry — site capability registry.

A single source of truth for "how we scrape each site": every tool can look up
the scrape method + confidence for a target site BEFORE it is called.

* ``site_catalog.domains``  — the static catalog DATA (typed entries).
* ``site_catalog.registry`` — ``SiteCatalog`` validated index + lookups
  (``coverage()``, ``get_site()``, ``recommend_method()``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from site_catalog.domains import CATALOG
from site_catalog.registry import (
    ANTI_BOT_LEVELS,
    DATA_DOMAINS,
    GENERIC_FALLBACK,
    METHOD_VOCABULARY,
    ROBOTS_STATES,
    SiteCatalog,
)

__all__ = [
    "ANTI_BOT_LEVELS",
    "CATALOG",
    "DATA_DOMAINS",
    "GENERIC_FALLBACK",
    "METHOD_VOCABULARY",
    "ROBOTS_STATES",
    "SiteCatalog",
]
