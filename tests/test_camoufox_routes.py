# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Camoufox SSRF validation: pre-navigation guard, route guard, error paths."""

from unittest.mock import patch

from pry.engine import camoufox_integration
from pry.engine.camoufox_integration import CamoufoxBrowser
from tests.camoufox_support import (  # noqa: F401 - helpers and fixtures
    _FakeRoute,
    _mock_camoufox_browser,
    _reset_camoufox_pool,
)


async def test_fetch_exception_returns_error_dict() -> None:
    mock_cls = _mock_camoufox_browser()
    mock_cls.__aenter__.return_value.goto.side_effect = RuntimeError("firefox crashed")

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("https://example.com")

    assert result["success"] is False
    assert "firefox crashed" in result["error"]


async def test_fetch_rejects_private_url_before_navigation() -> None:
    """The initial URL must be SSRF-validated before the browser navigates."""
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("http://169.254.169.254/latest/meta-data/")

    assert result["success"] is False
    browser.goto.assert_not_awaited()


async def test_fetch_installs_ssrf_route_guard() -> None:
    """The per-request route guard must be installed before navigation so the
    browser's internal redirect hops are re-validated too."""
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("https://example.com")

    assert result["success"] is True
    browser.route.assert_awaited_once()


async def test_guarded_route_aborts_metadata_request() -> None:
    route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_aborts_loopback_request() -> None:
    route = _FakeRoute("http://127.0.0.1:8080/admin")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_aborts_internal_hostname() -> None:
    route = _FakeRoute("http://kubernetes.default.svc.cluster.local/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_continues_public_request() -> None:
    route = _FakeRoute("https://example.com/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is False
    assert route.continued is True


async def test_guarded_route_continues_non_network_scheme() -> None:
    """data:/blob: URLs never touch the network — no SSRF surface, continue."""
    route = _FakeRoute("data:text/html,<h1>hi</h1>")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is False
    assert route.continued is True
