"""Shared fixtures and HTML samples for the UltimateScraper tier tests.

Split out of ``test_ultimate_scraper.py`` so each sibling module covers one
tier family and stays under the 200-line file gate.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import patch

import pytest

from pry.engine.ultimate_scraper import UltimateScraper, _browser_pool

VALID_HTML = "<html><body>" + "x" * 600 + "</body></html>"
VALID_HTML_2 = "<html><body>" + "y" * 600 + "</body></html>"
VALID_HTML_3 = "<html><body>" + "z" * 600 + "</body></html>"


@pytest.fixture(autouse=True)
def _pin_guard_resolver(resolved_dns: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the guard's historical resolver seam to the patched stdlib one.

    ``pry.engine.url_guard.socket`` re-exports ``getaddrinfo`` at import time,
    so patching ``socket.getaddrinfo`` only takes effect if the shim is
    imported afterwards. Any earlier tier test imports it first, leaving the
    real resolver bound and the pinned-URL routes unmocked. Rebinding here
    makes the respx tests order-independent.
    """
    import socket

    from pry.engine.url_guard import socket as guard_socket

    monkeypatch.setattr(guard_socket, "getaddrinfo", socket.getaddrinfo)


@pytest.fixture
def scraper() -> UltimateScraper:
    """Return a scraper with a clean registry mock so test pollution is impossible."""
    # Reset the module-level browser pool so a mocked driver/browser cached by
    # one test cannot leak into the next (the pool is a lazy singleton).
    _browser_pool.reset()
    with (
        patch(
            "pry.engine.ultimate_scraper.registry.reorder_for_domain", side_effect=lambda _d, c: c
        ),
        patch("pry.engine.ultimate_scraper.registry.is_service_allowed", return_value=True),
        patch("pry.engine.ultimate_scraper.registry.record_domain_tier_result"),
        patch("pry.engine.ultimate_scraper.registry.record_service_result"),
    ):
        yield UltimateScraper()
