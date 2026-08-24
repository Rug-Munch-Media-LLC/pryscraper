# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the multi-provider CAPTCHA solver.

Covers OCR preprocessing (with a mocked pytesseract), registry dispatch,
the 2captcha/Capsolver HTTP solve/poll loops (mocked httpx via respx —
no live network), and graceful ``None`` on missing API keys.
"""

import base64
import sys
import types
from io import BytesIO
from unittest.mock import Mock

import httpx
import pytest
import respx

from captcha import REGISTRY
from captcha.image_ocr import _normalize_image, ocr_image, preprocess_image
from captcha.token_api import solve_2captcha, solve_capsolver
from pry.core.settings import settings
from pry.engine.captcha_solver import available_providers, solve_captcha

EXPECTED_PROVIDERS = {"image", "recaptcha_v2", "recaptcha_v3", "hcaptcha", "turnstile"}


def _png_bytes() -> bytes:
    """Return a tiny valid PNG (8x8 white) for OCR preprocessing tests."""
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def _fake_pytesseract(monkeypatch, text: str = "K9F2") -> None:
    """Inject a fake pytesseract module so imports resolve without install."""
    fake = types.ModuleType("pytesseract")
    # mypy can't see dynamically-added attrs on a ModuleType — treat as Any.
    fake_any = fake  # type: ignore[var-annotated]
    fake_any.TesseractError = RuntimeError  # type: ignore[attr-defined]
    fake_any.image_to_string = Mock(return_value=f" {text} ")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", fake)


# ── registry / dispatch ──────────────────────────────────────────────────


def test_available_providers() -> None:
    assert set(available_providers()) == EXPECTED_PROVIDERS
    assert REGISTRY.keys() == EXPECTED_PROVIDERS


async def test_solve_unknown_type_returns_none() -> None:
    assert await solve_captcha("nonsense") is None


async def test_solve_disabled_toggle(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_enabled", False)
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "key")
    assert await solve_captcha("recaptcha_v2", sitekey="sk", url="https://x.test") is None


# ── image OCR ────────────────────────────────────────────────────────────


def test_normalize_image_accepts_bytes_base64_dataurl_and_path(tmp_path) -> None:
    raw = _png_bytes()
    assert _normalize_image(raw) == raw
    assert _normalize_image(base64.b64encode(raw).decode()) == raw
    assert _normalize_image(f"data:image/png;base64,{base64.b64encode(raw).decode()}") == raw
    path = tmp_path / "cap.png"
    path.write_bytes(raw)
    assert _normalize_image(str(path)) == raw
    assert _normalize_image(None) is None
    assert _normalize_image("") is None
    assert _normalize_image("not-base64!!") is None


def test_preprocess_image_returns_grayscale() -> None:
    img = preprocess_image(_png_bytes())
    assert img is not None
    assert img.mode == "L"


def test_preprocess_image_invalid_bytes() -> None:
    assert preprocess_image(b"not an image") is None


def test_ocr_image_with_mocked_tesseract(monkeypatch) -> None:
    _fake_pytesseract(monkeypatch, text="HELLO")
    img = preprocess_image(_png_bytes())
    assert img is not None
    assert ocr_image(img) == "HELLO"


async def test_solve_image_end_to_end_with_mocked_tesseract(monkeypatch) -> None:
    _fake_pytesseract(monkeypatch, text="ABC123")
    # bytes input
    assert await solve_captcha("image", image=_png_bytes()) == "ABC123"
    # base64 str input
    assert await solve_captcha("image", image=base64.b64encode(_png_bytes()).decode()) == "ABC123"


async def test_solve_image_missing_backend_returns_none() -> None:
    # pytesseract is NOT installed in the venv -> graceful None, no crash.
    assert await solve_captcha("image", image=_png_bytes()) is None


async def test_solve_image_no_image_returns_none() -> None:
    assert await solve_captcha("image") is None


# ── token providers: missing key -> None (no HTTP) ───────────────────────


async def test_token_providers_missing_key_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    for captcha_type in ("recaptcha_v2", "recaptcha_v3", "hcaptcha", "turnstile"):
        assert await solve_captcha(captcha_type, sitekey="sk", url="https://x.test") is None


async def test_token_providers_missing_sitekey_or_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "key")
    assert await solve_captcha("recaptcha_v2", sitekey="sk") is None
    assert await solve_captcha("recaptcha_v2", url="https://x.test") is None


# ── token_api: 2captcha solve/poll (mocked httpx) ────────────────────────


@respx.mock
async def test_solve_2captcha_success() -> None:
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "task-1"})
    )
    respx.get(url__startswith="https://2captcha.com/res.php").mock(
        side_effect=[
            httpx.Response(200, json={"status": 0, "request": "CAPCHA_NOT_READY"}),
            httpx.Response(200, json={"status": 1, "request": "TOKEN_XYZ"}),
        ]
    )
    token = await solve_2captcha(
        "test-key",
        "userrecaptcha",
        sitekey="sk",
        url="https://x.test",
        poll_interval=0.001,
        max_polls=5,
    )
    assert token == "TOKEN_XYZ"


@respx.mock
async def test_solve_2captcha_create_rejected() -> None:
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 0, "request": "ERROR_ZERO_BALANCE"})
    )
    token = await solve_2captcha(
        "test-key", "userrecaptcha", sitekey="sk", url="https://x.test", max_polls=1
    )
    assert token is None


@respx.mock
async def test_solve_2captcha_poll_timeout() -> None:
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "task-1"})
    )
    respx.get(url__startswith="https://2captcha.com/res.php").mock(
        return_value=httpx.Response(200, json={"status": 0, "request": "CAPCHA_NOT_READY"})
    )
    token = await solve_2captcha(
        "test-key",
        "userrecaptcha",
        sitekey="sk",
        url="https://x.test",
        poll_interval=0.001,
        max_polls=2,
    )
    assert token is None


# ── token_api: Capsolver solve/poll (mocked httpx) ───────────────────────


@respx.mock
async def test_solve_capsolver_success() -> None:
    respx.post("https://api.capsolver.com/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 0, "taskId": "caps-task"})
    )
    respx.post("https://api.capsolver.com/getTaskResult").mock(
        side_effect=[
            httpx.Response(200, json={"status": "processing", "errorId": 0}),
            httpx.Response(
                200,
                json={
                    "status": "ready",
                    "errorId": 0,
                    "solution": {"gRecaptchaResponse": "CAP_TOKEN"},
                },
            ),
        ]
    )
    token = await solve_capsolver(
        "test-key",
        "ReCaptchaV2Task",
        sitekey="sk",
        url="https://x.test",
        poll_interval=0.001,
        max_polls=5,
    )
    assert token == "CAP_TOKEN"


@respx.mock
async def test_solve_capsolver_create_failed() -> None:
    respx.post("https://api.capsolver.com/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 1, "errorDescription": "key invalid"})
    )
    token = await solve_capsolver(
        "test-key", "ReCaptchaV2Task", sitekey="sk", url="https://x.test", max_polls=1
    )
    assert token is None


# ── provider dispatch with keys set (mocked httpx) ───────────────────────


@respx.mock
async def test_solve_captcha_recaptcha_v2_via_2captcha(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "test-key")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "task-1"})
    )
    respx.get(url__startswith="https://2captcha.com/res.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "V2_TOKEN"})
    )
    token = await solve_captcha("recaptcha_v2", sitekey="sk", url="https://x.test")
    assert token == "V2_TOKEN"


@respx.mock
async def test_solve_captcha_recaptcha_v3_uses_action_and_min_score(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "test-key")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "task-1"})
    )
    respx.get(url__startswith="https://2captcha.com/res.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "V3_TOKEN"})
    )
    token = await solve_captcha("recaptcha_v3", sitekey="sk", url="https://x.test")
    assert token == "V3_TOKEN"
    sent = respx.calls[0].request.content.decode()
    assert "action=verify" in sent
    assert "min_score=0.3" in sent


@respx.mock
async def test_solve_captcha_hcaptcha_via_capsolver(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "caps-key")
    respx.post("https://api.capsolver.com/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 0, "taskId": "caps-task"})
    )
    respx.post("https://api.capsolver.com/getTaskResult").mock(
        return_value=httpx.Response(
            200,
            json={"status": "ready", "errorId": 0, "solution": {"gRecaptchaResponse": "HCAP"}},
        )
    )
    token = await solve_captcha("hcaptcha", sitekey="sk", url="https://x.test")
    assert token == "HCAP"
    sent = respx.calls[0].request.content.decode()
    assert "HCaptchaTask" in sent


@respx.mock
async def test_solve_captcha_turnstile_via_capsolver(monkeypatch) -> None:
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "caps-key")
    respx.post("https://api.capsolver.com/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 0, "taskId": "caps-task"})
    )
    respx.post("https://api.capsolver.com/getTaskResult").mock(
        return_value=httpx.Response(
            200,
            json={"status": "ready", "errorId": 0, "solution": {"token": "TURNSTILE_TOKEN"}},
        )
    )
    token = await solve_captcha("turnstile", sitekey="sk", url="https://x.test")
    assert token == "TURNSTILE_TOKEN"
    sent = respx.calls[0].request.content.decode()
    assert "TurnstileTask" in sent


# ---------------------------------------------------------------------------
# Fallback chain tests
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_solve_token_with_fallback_2captcha_first(monkeypatch) -> None:
    """Should use 2captcha when key is set and capsolver is also set."""
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "2cap-key")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "caps-key")
    respx.post("https://2captcha.com/in.php").mock(
        return_value=httpx.Response(200, json={"status": 1, "request": "123"})
    )
    respx.get(
        httpx.URL("https://2captcha.com/res.php").copy_with(
            params={"key": "2cap-key", "action": "get", "id": "123", "json": 1}
        )
    ).mock(return_value=httpx.Response(200, json={"status": 1, "request": "TOKEN_2CAPTCHA"}))
    from captcha.token_api import solve_token_with_fallback

    token = await solve_token_with_fallback("recaptcha_v2", sitekey="sk", url="https://x.test")
    assert token == "TOKEN_2CAPTCHA"


@respx.mock
@pytest.mark.asyncio
async def test_solve_token_with_fallback_falls_to_capsolver(monkeypatch) -> None:
    """Should fallback to capsolver when 2captcha key is empty."""
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "caps-key")
    respx.post("https://api.capsolver.com/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 0, "taskId": "t1"})
    )
    respx.post("https://api.capsolver.com/getTaskResult").mock(
        return_value=httpx.Response(
            200, json={"status": "ready", "solution": {"gRecaptchaResponse": "CAPS_TOKEN"}}
        )
    )
    from captcha.token_api import solve_token_with_fallback

    token = await solve_token_with_fallback("recaptcha_v2", sitekey="sk", url="https://x.test")
    assert token == "CAPS_TOKEN"


@pytest.mark.asyncio
async def test_solve_token_with_fallback_all_fail_returns_none(monkeypatch) -> None:
    """Should return None when all providers have no keys."""
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    from captcha.token_api import solve_token_with_fallback

    token = await solve_token_with_fallback("recaptcha_v2", sitekey="sk", url="https://x.test")
    assert token is None


@pytest.mark.asyncio
async def test_solve_token_with_fallback_unknown_type_returns_none() -> None:
    """Should return None for unknown captcha types."""
    from captcha.token_api import solve_token_with_fallback

    token = await solve_token_with_fallback("unknown_type", sitekey="sk", url="https://x.test")
    assert token is None


@respx.mock
@pytest.mark.asyncio
async def test_solve_deathbycaptcha_success(monkeypatch) -> None:
    """DeathByCaptcha should return a token on success."""
    from captcha.token_api import solve_deathbycaptcha

    respx.post("https://api.deathbycaptcha.com/api/captcha").mock(
        return_value=httpx.Response(200, json={"status": 1, "text": "DBC_TOKEN"})
    )
    token = await solve_deathbycaptcha("user", "pass", sitekey="sk", url="https://x.test")
    assert token == "DBC_TOKEN"


@pytest.mark.asyncio
async def test_solve_deathbycaptcha_missing_creds() -> None:
    """Should return None when username/password are empty."""
    from captcha.token_api import solve_deathbycaptcha

    token = await solve_deathbycaptcha("", "", sitekey="sk", url="https://x.test")
    assert token is None


@respx.mock
@pytest.mark.asyncio
async def test_solve_nextcaptcha_success(monkeypatch) -> None:
    """NextCaptcha should return a token on success."""
    from captcha.token_api import solve_nextcaptcha

    respx.post("https://api.nextcaptcha.com/v1/createTask").mock(
        return_value=httpx.Response(200, json={"errorId": 0, "taskId": "nc1"})
    )
    respx.post("https://api.nextcaptcha.com/v1/getTaskResult").mock(
        return_value=httpx.Response(
            200, json={"status": "ready", "solution": {"token": "NC_TOKEN"}}
        )
    )
    token = await solve_nextcaptcha("nc-key", "ReCaptchaV2Task", sitekey="sk", url="https://x.test")
    assert token == "NC_TOKEN"


@pytest.mark.asyncio
async def test_solve_nextcaptcha_missing_key() -> None:
    """Should return None when API key is empty."""
    from captcha.token_api import solve_nextcaptcha

    token = await solve_nextcaptcha("", "ReCaptchaV2Task", sitekey="sk", url="https://x.test")
    assert token is None
