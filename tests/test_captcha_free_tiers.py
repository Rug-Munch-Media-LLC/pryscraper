"""Each free tier degrades to a typed reason instead of crashing or hanging."""

from __future__ import annotations

import pytest

from pry.engine.captcha import audio_asr, browser_integrity, image_ocr, t0_profile, vision


def test_image_bytes_normalisation_accepts_data_urls() -> None:
    assert image_ocr._normalize_image("data:image/png;base64,QUJD") == b"ABC"
    assert image_ocr._normalize_image(None) is None
    assert image_ocr._normalize_image("not base64 !!") is None


@pytest.mark.asyncio
async def test_audio_without_model_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(audio_asr.MODEL_ENV, "/nonexistent/asr-model")
    assert audio_asr.capability() is False
    assert await audio_asr.solve_audio(b"clip") == (
        None,
        "unavailable.model:/nonexistent/asr-model",
    )
    assert await audio_asr.solve_audio(None) == (None, "not_applicable")


@pytest.mark.asyncio
async def test_vision_refuses_unsupported_classes() -> None:
    assert await vision.solve_puzzle(b"bg", b"piece", "grid") == (None, "unsupported.class")
    assert await vision.solve_puzzle(None, None, "slider") == (None, "not_applicable")


@pytest.mark.asyncio
async def test_ocr_without_model_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(image_ocr.MODEL_ENV, "/nonexistent/common.onnx")
    assert image_ocr.capability() is False
    assert await image_ocr.solve_image(b"img") == (
        None,
        "unavailable.model:/nonexistent/common.onnx",
    )


@pytest.mark.asyncio
async def test_t0_clean_profile_without_curl_cffi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(t0_profile, "capability", lambda: False)
    assert await t0_profile.fetch_clean("https://example.com") == (None, "unavailable.model")


@pytest.mark.asyncio
async def test_browser_integrity_reports_unavailable_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_integrity, "_engine", lambda: None)
    monkeypatch.setattr(browser_integrity, "chrome_path", lambda: None)
    assert browser_integrity.capability() is False
    assert await browser_integrity.solve_browser("https://example.com", "turnstile") == (
        None,
        "unavailable.browser",
    )
