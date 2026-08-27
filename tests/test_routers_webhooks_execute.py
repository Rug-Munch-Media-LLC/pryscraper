# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for routers/webhooks.py and routers/execute.py.

Webhooks: test-delivery endpoint must surface the fail-closed refusal when
no signing secret is configured; dead-letter queue read-only endpoint.
Execute: Pryfile runner with directory-traversal protection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

import pry.api.routers.integrations.webhooks as webhooks_module
from pry.api.routers.integrations.webhooks import router as webhooks_router
from pry.api.routers.scraping.execute import _safe_pryfile_path, router as execute_router
from pry.core.errors import InvalidRequestError, PryError

if TYPE_CHECKING:
    from pathlib import Path


def _add_pry_error_handler(a: FastAPI) -> None:
    """Mirror api.py's PryError -> JSONResponse(status_code) mapping."""

    @a.exception_handler(PryError)
    async def handler(request: object, exc: PryError) -> object:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@pytest.fixture
def webhook_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Webhooks router app with isolated data dir and NO signing secret."""
    monkeypatch.setattr(webhooks_module, "__name__", webhooks_module.__name__)
    a = FastAPI()
    _add_pry_error_handler(a)
    a.include_router(webhooks_router)
    return TestClient(a, raise_server_exceptions=False)


# ── Webhooks router ──────────────────────────────────────────────────────────


class TestWebhookTestEndpoint:
    @respx.mock
    def test_delivery_success_with_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "wh")
        monkeypatch.setattr("pry.api.webhook_delivery.settings.webhook_secret", "secret-1")
        respx.post("http://hook.example.com").mock(return_value=Response(200, json={"ok": True}))
        a = FastAPI()
        a.include_router(webhooks_router)
        client = TestClient(a, raise_server_exceptions=False)
        r = client.post(
            "/v1/webhooks/test",
            json={"url": "http://hook.example.com", "payload": {"event": "x"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["status"] == 200
        assert body["attempts"] == 1

    def test_delivery_refused_without_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed contract surfaced through the HTTP boundary."""
        monkeypatch.setattr("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "wh2")
        monkeypatch.setattr("pry.api.webhook_delivery.settings.webhook_secret", "")
        a = FastAPI()
        a.include_router(webhooks_router)
        client = TestClient(a, raise_server_exceptions=False)
        r = client.post("/v1/webhooks/test", json={"url": "http://hook.example.com"})
        assert r.status_code == 200  # delivery result is a payload, not an HTTP error
        body = r.json()
        assert body["success"] is False
        assert body.get("refused") is True

    def test_missing_url_is_422(self, webhook_client: TestClient) -> None:
        r = webhook_client.post("/v1/webhooks/test", json={})
        assert r.status_code == 422


class TestDeadLetterEndpoint:
    def test_empty_queue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "wh3")
        monkeypatch.setattr("pry.api.webhook_delivery.settings.webhook_secret", "s")
        a = FastAPI()
        a.include_router(webhooks_router)
        client = TestClient(a, raise_server_exceptions=False)
        r = client.get("/v1/webhooks/dead-letter")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []


# ── Execute router ───────────────────────────────────────────────────────────


class TestSafePryfilePath:
    def test_relative_path_inside_cwd_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        pryfile = tmp_path / "pry.yml"
        pryfile.write_text("jobs: []\n")
        resolved = _safe_pryfile_path("pry.yml")
        assert resolved == str(pryfile.resolve())

    def test_traversal_outside_cwd_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(InvalidRequestError):
            _safe_pryfile_path("../../etc/passwd")

    def test_missing_file_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(InvalidRequestError, match="File not found"):
            _safe_pryfile_path("does-not-exist.yml")

    def test_directory_instead_of_file_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "adir").mkdir()
        with pytest.raises(InvalidRequestError, match="File not found"):
            _safe_pryfile_path("adir")


class TestRunPryfileEndpoint:
    def test_run_returns_job_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pry.yml").write_text("jobs: []\n")

        class _FakePryfile:
            def __init__(self, path: str) -> None:
                pass

            async def run_all(self, scraper: object) -> list[dict[str, int]]:
                return [{"job": "a", "status": 200}]

        import pry.misc.pryfile as pryfile_module

        monkeypatch.setattr(pryfile_module, "Pryfile", _FakePryfile)
        a = FastAPI()
        _add_pry_error_handler(a)
        a.include_router(execute_router)
        client = TestClient(a, raise_server_exceptions=False)
        r = client.post("/v1/run", json={"path": "pry.yml"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["jobs"][0]["job"] == "a"

    def test_traversal_via_http_is_400(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        a = FastAPI()
        _add_pry_error_handler(a)
        a.include_router(execute_router)
        client = TestClient(a, raise_server_exceptions=False)
        r = client.post("/v1/run", json={"path": "../../../etc/passwd"})
        assert r.status_code == 400
