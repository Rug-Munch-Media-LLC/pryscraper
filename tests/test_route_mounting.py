"""Route-mounting regression tests (registry vs the composed application).

A router can import cleanly, expose handlers, and still 404 in production when
``router_registry`` never imports or mounts it — the failure is invisible to a
test that mounts the router directly. These tests assert against the composed
app instead.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from fastapi.routing import APIRoute

from pry.api import router_registry
from pry.api.api import app

# The site catalog publishes these three paths; only the composed app decides
# whether they are reachable.
COVERAGE_PATHS = {
    "/v1/coverage",
    "/v1/coverage/recommend",
    "/v1/coverage/{site_id}",
}


def _app_paths() -> set[str]:
    """Every path the assembled app serves (included routers resolved)."""
    return set(app.openapi()["paths"])


def test_site_catalog_router_is_registered() -> None:
    """The registry imports the router that owns /v1/coverage*."""
    assert hasattr(router_registry, "site_catalog_router")


def test_coverage_routes_are_mounted() -> None:
    """All three coverage endpoints are reachable on the composed app."""
    missing = COVERAGE_PATHS - _app_paths()
    assert not missing, f"unmounted coverage routes: {sorted(missing)}"


def test_every_registry_router_exposes_a_mounted_path() -> None:
    """No router imported by the registry is left unmounted.

    Routers without schema-visible APIRoutes (WebSocket streams, hidden ops
    endpoints) are skipped: they are not representable in the OpenAPI paths.
    """
    paths = _app_paths()
    unmounted: list[str] = []
    for name, router in vars(router_registry).items():
        if not name.endswith("_router") or router is None:
            continue
        visible = {
            route.path
            for route in getattr(router, "routes", [])
            if isinstance(route, APIRoute) and route.include_in_schema
        }
        if visible and not (visible & paths):
            unmounted.append(name)
    assert not unmounted, f"routers imported but never mounted: {sorted(unmounted)}"
