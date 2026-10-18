"""Ops surface authorization: /metrics and the docs endpoints.

/metrics exposes process internals, so in prod it answers only loopback scrapers
or a caller holding PRY_OPS_TOKEN. /docs and /openapi.json are not mounted in
prod at all and must 404 rather than advertise the API surface.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import pytest
from fastapi.testclient import TestClient

REMOTE = ("203.0.113.9", 51234)
LOOPBACK = ("127.0.0.1", 51234)


def _settings() -> object:
    import pry.core.settings as settings_mod

    return settings_mod.settings


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prod-like settings: no API key, no ops token, environment == prod."""
    settings = _settings()
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.delenv("PRY_OPS_TOKEN", raising=False)


@pytest.fixture
def dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev-like settings with the same credential surface as prod."""
    settings = _settings()
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.delenv("PRY_OPS_TOKEN", raising=False)


def _app():
    """The composed app; ops policy is evaluated per request, not at import."""
    from pry.api.api import app

    return app


def test_metrics_rejects_anonymous_remote_caller_in_prod(prod: None) -> None:
    app = _app()
    response = TestClient(app, client=REMOTE).get("/metrics")
    assert response.status_code in (401, 403)


def test_metrics_allows_loopback_scraper_in_prod(prod: None) -> None:
    app = _app()
    response = TestClient(app, client=LOOPBACK).get("/metrics")
    assert response.status_code == 200


def test_metrics_is_open_in_dev(dev: None) -> None:
    app = _app()
    response = TestClient(app, client=REMOTE).get("/metrics")
    assert response.status_code == 200


def test_docs_and_openapi_are_404_in_prod(prod: None) -> None:
    app = _app()
    client = TestClient(app, client=REMOTE)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_are_served_in_dev(dev: None) -> None:
    app = _app()
    client = TestClient(app, client=REMOTE)
    assert client.get("/docs").status_code == 200
