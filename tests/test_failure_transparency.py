"""Failure-transparency tests: swallowed transport errors must stay visible.

Covers three call sites that used to return a plausible empty/success value
when the underlying transport failed:
  - PryScraper._extract_links / map_urls  (src/pry/engine/scraper.py)
  - POST /v1/emails                        (routers/scraping/extraction.py)
  - CamoufoxBrowser.fetch_with_stealth     (src/pry/engine/camoufox_integration.py)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.scraping.extraction import router
from pry.engine.camoufox_integration import CamoufoxBrowser
from pry.engine.scraper import PryScraper


class _Boom(OSError):
    """Distinct transport failure type so the message is attributable."""


# ── scraper.py: map_urls / _extract_links / crawl ───────────────────────────


async def test_map_urls_raises_naming_both_transport_errors() -> None:
    """Both transports failing must raise, not return [] (which means 'no links')."""
    s = PryScraper()
    s._fetch_direct = AsyncMock(side_effect=_Boom("direct-down"))  # type: ignore[method-assign]
    s._fetch_via_flaresolverr = AsyncMock(side_effect=_Boom("flaresolverr-down"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as exc:
        await s.map_urls("https://example.com", {"limit": 5})

    msg = str(exc.value)
    assert "direct" in msg
    assert "direct-down" in msg
    assert "flaresolverr" in msg
    assert "flaresolverr-down" in msg


async def test_crawl_records_status_error_instead_of_silently_skipping() -> None:
    """A page whose scrape raises is recorded, not dropped by a bare continue."""
    s = PryScraper()
    s.scrape = AsyncMock(side_effect=_Boom("scrape-exploded"))  # type: ignore[method-assign]
    s._extract_links = AsyncMock(return_value=[])  # type: ignore[method-assign]

    results = await s.crawl("https://example.com", {"max_pages": 1, "max_depth": 0})

    assert len(results) == 1
    entry = results[0]
    assert entry["status"] == "error"
    assert entry["url"] == "https://example.com"
    assert "scrape-exploded" in entry["error"]


# ── extraction.py: /v1/emails social_error ─────────────────────────────────


def test_emails_endpoint_reports_social_error_when_direct_fetch_fails() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    failing = AsyncMock()
    failing.get = AsyncMock(side_effect=httpx.ConnectError("dns went away"))

    scrape_result: dict[str, Any] = {"status": "ok", "content": "reach us at a@b.com"}
    with (
        patch("pry.api.routers.scraping.extraction.get_client", return_value=failing),
        # The SSRF fix routes the direct fetch through guard_get, which owns the
        # request/redirect loop. Patching only get_client leaves the guard on the
        # real path, so the transport error under test is never produced.
        patch(
            "pry.api.routers.scraping.extraction.guard_get",
            AsyncMock(side_effect=httpx.ConnectError("dns went away")),
        ),
        patch(
            "pry.api.routers.scraping.extraction.scraper.scrape",
            AsyncMock(return_value=scrape_result),
        ),
    ):
        r = client.post("/v1/emails", data={"url": "https://example.com"})

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["emails"], "emails come from the multi-tier scraper and are unaffected"
    assert not data["social"], "no social links could be found on an unfetched page"
    assert data["social_error"] is not None
    assert "ConnectError" in data["social_error"]
    assert "dns went away" in data["social_error"]


# ── camoufox_integration.py: human_behavior_applied ─────────────────────────


async def test_fetch_with_stealth_flags_never_applied_human_behaviour() -> None:
    """Direct-path success must not look like a completed stealth pass."""
    b = CamoufoxBrowser()
    direct: dict[str, Any] = {
        "success": True,
        "url": "https://example.com",
        "content": "<html>direct</html>",
    }

    with patch.object(CamoufoxBrowser, "fetch", AsyncMock(return_value=direct)):
        result = await b.fetch_with_stealth("https://example.com", {"scroll": [100, 400]})

    assert result["success"] is True
    assert result["content"] == "<html>direct</html>"
    assert result["human_behavior_applied"] is False
    assert result["human_behavior_error"] is not None
