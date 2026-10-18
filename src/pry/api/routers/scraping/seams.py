"""Pry — resolve the scraping routes' shared bindings at call time.

``scraping.py`` owns the singleton bindings (``scraper``, ``cache``,
``extractor``, ``queue``, ``get_client``). Importing them here at module level
would be circular (``scraping.py`` imports the route modules to compose the
router), and resolving on call preserves the existing test seam: tests patch
``pry.api.routers.scraping.scraping.scraper``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any


def bindings() -> Any:
    """Return the composition module holding the live bindings."""
    from pry.api.routers.scraping import scraping

    return scraping
