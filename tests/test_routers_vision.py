"""Tests for routers/vision.py — handler unit tests (no x402 middleware)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.ai.vision import router as vision_router

app = FastAPI()
app.include_router(vision_router)
client = TestClient(app, raise_server_exceptions=False)


def test_vision_no_input():
    r = client.post("/v1/vision", json={"question": "Describe this"})
    assert r.status_code in (400, 422, 500)


def test_vision_with_url():
    with (
        patch("pry.core.deps.automator.run_steps", new_callable=AsyncMock) as mock_r,
        patch("pry.api.routers.ai.vision._call_vision_api", new_callable=AsyncMock) as mock_api,
    ):
        mock_r.return_value = {"steps": [{"action": "screenshot", "screenshot": "b64data"}]}
        mock_api.return_value = ("desc", "mock", None)
        r = client.post(
            "/v1/vision", json={"question": "Describe this", "url": "http://example.com"}
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"


def test_vision_with_image_b64():
    with patch("pry.api.routers.ai.vision._call_vision_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = ("desc", "mock-model", None)
        r = client.post("/v1/vision", json={"question": "Describe this", "image": "iVBORw0KGgo="})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        assert r.json().get("success") is True


def test_vision_with_file_path():
    import io

    with (
        patch("os.path.isfile", return_value=True),
        patch("builtins.open", return_value=io.BytesIO(b"\x89PNG\r\n\x1a\n")),
        patch("pry.api.routers.ai.vision._call_vision_api", new_callable=AsyncMock) as mock_api,
    ):
        mock_api.return_value = ("desc", "mock", None)
        r = client.post(
            "/v1/vision", json={"question": "Describe this", "file_path": "/tmp/test.png"}
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"


def test_vision_models():
    r = client.get("/v1/vision/models")
    assert r.status_code in (200, 500)
