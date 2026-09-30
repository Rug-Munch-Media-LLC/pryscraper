"""Router smoke test — imports every routers/*.py module and asserts it
registers a valid APIRouter carrying at least one route.

Safety net for the package-migration wins (SYSTEM-AUDIT-V2-50-WINS A1-A6):
a broken import or a module that silently loses its ``router`` attribute
fails HERE in seconds, instead of surfacing as a runtime 500 or a route
that quietly disappears from the OpenAPI schema.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi import APIRouter

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "src" / "pry" / "api" / "routers"


def _router_modules() -> list[str]:
    """Every router module under routers/ at any depth (excluding __init__)."""
    modules: list[str] = []
    for p in sorted(ROUTERS_DIR.rglob("*.py")):
        if p.stem == "__init__":
            continue
        rel = p.relative_to(ROUTERS_DIR).with_suffix("")
        name = ".".join(rel.parts)
        if name in NON_ROUTER_HELPERS:
            continue
        modules.append(name)
    return modules


# Shared-helper modules under routers/ that intentionally expose no APIRouter.
# Keep this list tiny: a module that stops exposing `router` because of a bug
# must fail this test, not get parked here.
NON_ROUTER_HELPERS = {
    # In-memory issue tracker extracted from admin_shared; it exposes no router
    # by design, same shape as the entries below.
    "core.admin_issues_store",
    "commerce.billing_subscription.models",
    "commerce.billing_subscription.state",
    "commerce.hosting.auth",
    "commerce.hosting.models",
    "core.admin_shared",
    "ai.vision_keys",
    "core.admin_html_rows",
    "commerce.x402_engines",
    "scraping.scraping_models",
    "scraping.crawl_adaptive",
    "scraping.extraction_llm",
    # SSRF-guarded fetch helper shared by the scraping routers; it exposes no
    # router by design — the routers that call it are still covered below.
    "scraping.fetch",
    # Owner derivation for the credential routes; pure logic, no router.
    "core.credential_scope",
}


MODULES = _router_modules()


def test_all_router_modules_discovered() -> None:
    """Guard against the discovery itself rotting (dir moved/renamed)."""
    assert len(MODULES) >= 80, f"expected ~82 router modules, found {len(MODULES)}: {MODULES[:5]}…"


@pytest.mark.parametrize("module_name", MODULES)
def test_router_module_imports_and_registers(module_name: str) -> None:
    mod = importlib.import_module(f"pry.api.routers.{module_name}")
    router = getattr(mod, "router", None)
    assert isinstance(router, APIRouter), (
        f"pry/api/routers/{module_name}.py does not expose an APIRouter named `router`"
    )
    assert len(router.routes) > 0, f"pry/api/routers/{module_name}.py registers zero routes"
