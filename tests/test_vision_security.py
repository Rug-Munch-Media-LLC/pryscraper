"""Security regression tests for the /v1/vision surface."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pry.api.routers.ai import vision, vision_keys
from pry.core.errors import PryError
from pry.engine.resilience import registry
from pry.payments.x402_middleware import X402Middleware
from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    classify_path,
    resolve_operation,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(vision.router)

    @app.exception_handler(PryError)
    async def _pry_error(_request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    return app


client = TestClient(_app(), raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_breaker():
    breaker = registry.breaker("openrouter")
    saved = (breaker.state, breaker.failures, breaker.last_failure_at)
    breaker.state = "closed"
    breaker.failures = 0
    breaker.half_open_attempts = 0
    yield
    breaker.state, breaker.failures, breaker.last_failure_at = saved


def test_arbitrary_file_read_is_rejected_before_dispatch():
    with patch.object(vision, "_call_vision_api", new_callable=AsyncMock) as api:
        for target in ("/etc/passwd", "~/.hermes/.env"):
            response = client.post("/v1/vision", json={"file_path": target})
            assert response.status_code in (400, 422)
    api.assert_not_awaited()


def test_paid_model_is_rejected():
    with patch.object(vision, "_call_vision_api", new_callable=AsyncMock) as api:
        response = client.post("/v1/vision", json={"image": "aGk=", "model": "openai/gpt-4o"})
    assert response.status_code == 400
    api.assert_not_awaited()


def test_max_tokens_is_clamped():
    with patch.object(vision, "_call_vision_api", new_callable=AsyncMock) as api:
        api.return_value = ("desc", "mock", None)
        response = client.post(
            "/v1/vision", json={"image": "aGk=", "max_tokens": 999999, "no_fallback": True}
        )
    assert response.status_code == 200
    assert api.await_args.args[3] == vision.MAX_VISION_TOKENS


def test_unknown_fields_are_rejected():
    response = client.post("/v1/vision", json={"image": "aGk=", "admin": True})
    assert response.status_code == 422


def test_vision_is_paid_while_models_listing_is_free():
    assert "/v1/vision" not in DEFAULT_FREE_PATHS
    assert "/v1/vision/models" in DEFAULT_FREE_PATHS
    assert classify_path("/v1/vision") == "paid"
    assert resolve_operation("/v1/vision") == "llm_call"
    assert classify_path("/v1/vision/models") == "free"


def test_vision_without_payment_is_challenged():
    app = _app()
    app.add_middleware(X402Middleware, wallet="0x0", network="base")
    gated = TestClient(app, raise_server_exceptions=False)
    response = gated.post("/v1/vision", json={"image": "aGk="})
    assert response.status_code in (402, 403)


def test_breaker_opens_after_failures_and_returns_503():
    for _ in range(5):
        registry.record_service_result("openrouter", False)
    assert registry.is_service_allowed("openrouter") is False
    with patch.object(vision, "_call_vision_api", new_callable=AsyncMock) as api:
        response = client.post("/v1/vision", json={"image": "aGk="})
    assert response.status_code == 503
    api.assert_not_awaited()


def test_failure_records_breaker_and_does_not_echo_upstream_body():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    upstream = httpx.Response(500, request=request, text="SECRET-UPSTREAM-BODY")
    error = httpx.HTTPStatusError("boom", request=request, response=upstream)
    with patch.object(vision, "_call_vision_api", side_effect=error):
        response = client.post("/v1/vision", json={"image": "aGk=", "no_fallback": True})
    assert response.status_code == 502
    assert "SECRET-UPSTREAM-BODY" not in response.text
    assert "http_500" in response.text


@pytest.mark.asyncio
async def test_transport_failure_increments_breaker(monkeypatch):
    class _FailingClient:
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("down")

    async def _client():
        return _FailingClient()

    monkeypatch.setattr(vision_keys, "_get_or_key", lambda: "sk-test")
    monkeypatch.setattr(vision, "get_client", _client)
    before = registry.breaker("openrouter").failures
    with pytest.raises(httpx.ConnectError):
        await vision._call_vision_api("aGk=", "what?", "openrouter/free")
    assert registry.breaker("openrouter").failures == before + 1
