"""Pry — attention & SEO intelligence package.

SERP rank tracking (organic + AI Overview + People Also Ask), Google
Trends interest, and Meta Ad Library ad intelligence — all built on free,
public, keyless endpoints.

Modules (each *never raises*; they return ``[]`` / ``{}`` / ``None`` on
any failure):

* :mod:`attention.serp`     — ``serp(query, num=10)``
* :mod:`attention.trends`   — ``trend_interest(keyword, timeframe)``
* :mod:`attention.ad_intel` — ``search_ads(page_name, country, limit)``

Submodules are imported lazily (the router uses ``importlib``) so this
package stays import-light; nothing pulls in httpx/lxml at package
import time.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

__version__ = "1.0.0"
