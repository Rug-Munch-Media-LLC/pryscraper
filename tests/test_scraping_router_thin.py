"""Architecture tests: the scraping routers stay thin.

* The composed scraping router and its per-resource modules reach the engine
  only through the service seam (``pry.engine.scraping_service``) — never
  through engine internals.
* Every original path is still registered on the composed app, exactly once.
* Scrape-format / map / search parity behaviour still works end to end.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app

if TYPE_CHECKING:
    from collections.abc import Iterator

ROUTERS = Path(__file__).resolve().parents[1] / "src/pry/api/routers"
SCRAPING = "pry.api.routers.scraping.scraping"
SERVICE_SEAM = "pry.engine.scraping_service"
ROUTE_MODULES = (
    "scraping",
    "scrape_routes",
    "crawl_map_routes",
    "batch_routes",
    "detect_routes",
    "seams",
    "http_guards",
)
ORIGINAL_PATHS = (
    "/v1/scrape",
    "/v1/detect-block",
    "/v1/capture/lazy",
    "/v1/crawl",
    "/v1/batch",
    "/v1/map",
    "/v1/search",
)

HTML = """<html><head><title>Example</title></head><body>
<article><h1>Hello</h1><p>Body text.</p></article>
<a href="/a">A</a><a href="https://other.example/b">B</a><a href="/a">dup</a>
<img src="/img/x.png"><img src="data:image/png;base64,AAA">
<a href="mailto:x@example.com">mail</a>
</body></html>"""

RESULT: dict[str, Any] = {
    "status": "ok",
    "url": "https://example.com",
    "title": "Example",
    "description": "An example page",
    "content": "# Hello\n\nBody text.",
    "raw_html": HTML,
    "method": "direct",
    "markdown_quality": 0.9,
}


def _engine_imports(path: Path) -> set[str]:
    """Every ``pry.engine`` module imported anywhere in one file (AST)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "pry.engine" or node.module.startswith("pry.engine."):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pry.engine" or alias.name.startswith("pry.engine."):
                    found.add(alias.name)
    return found


def test_route_modules_import_only_the_service_seam() -> None:
    offenders: dict[str, list[str]] = {}
    for name in ROUTE_MODULES:
        extra = _engine_imports(ROUTERS / "scraping" / f"{name}.py") - {SERVICE_SEAM}
        if extra:
            offenders[name] = sorted(extra)
    assert not offenders, f"engine imports outside the service seam: {offenders}"


def test_composition_module_has_no_engine_imports() -> None:
    assert _engine_imports(ROUTERS / "scraping" / "scraping.py") == set()


def test_original_paths_registered_exactly_once() -> None:
    paths = app.openapi()["paths"]
    missing = [path for path in ORIGINAL_PATHS if path not in paths]
    assert not missing, f"routes disappeared: {missing}"
    duplicated = [path for path in ORIGINAL_PATHS if len(paths[path]) != 1]
    assert not duplicated, f"routes with extra operations (double registration): {duplicated}"


@pytest.fixture(autouse=True)
def clear_response_cache() -> Iterator[None]:
    from pry.core.deps import cache as response_cache

    response_cache.clear()
    yield
    response_cache.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield TestClient(app)


def test_scrape_formats_parity(client: TestClient) -> None:
    with patch(f"{SCRAPING}.scraper.scrape", AsyncMock(return_value=dict(RESULT))):
        response = client.post(
            "/v1/scrape",
            json={"url": "https://example.com", "formats": ["links", "images", "rawHtml"]},
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["links"] == ["https://example.com/a", "https://other.example/b"]
    assert data["images"] == [
        "https://example.com/img/x.png",
        "data:image/png;base64,AAA",
    ]
    assert data["rawHtml"] == HTML


def test_map_parity(client: TestClient) -> None:
    sitemap = """<?xml version="1.0"?><urlset>
        <url><loc>https://example.com/a</loc></url>
        <url><loc>https://example.com/a#section</loc></url>
        <url><loc>https://example.com/b</loc></url>
        <url><loc>https://other.example/x</loc></url>
    </urlset>"""

    class _FakeResponse:
        text = sitemap
        status_code = 200

    module = "pry.api.routers.scraping.search_map"
    with (
        patch(f"{module}.validate_url_async", AsyncMock(side_effect=lambda u: u)),
        patch(f"{module}.safe_get", AsyncMock(return_value=_FakeResponse())),
    ):
        response = client.post("/v1/map", json={"url": "https://example.com", "limit": 50})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert body["links"] == [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}]


def test_search_parity(client: TestClient) -> None:
    payload = {"results": [{"url": "https://example.com/a", "title": "A", "snippet": "first"}]}
    module = "pry.api.routers.scraping.search_map"
    with patch(f"{module}.search_web", AsyncMock(return_value=payload)):
        response = client.post("/v1/search", json={"query": "pry api", "limit": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "pry api"
    assert body["results"] == [
        {"url": "https://example.com/a", "title": "A", "description": "first"}
    ]
