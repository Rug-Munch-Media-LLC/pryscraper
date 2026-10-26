"""Proxy, CAPTCHA, and LLM capability detection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging

from pry.api.capabilities import probes
from pry.core.settings import settings

logger = logging.getLogger(__name__)


def _proxy_capability() -> tuple[bool, str, list[str]]:
    """Detect whether egress is routed through a proxy.

    Reports a boolean plus a provider tag only — never the proxy URL or any
    credential material.
    """
    if settings.tor_enabled:
        return True, "tor", []
    if settings.proxy_enabled and settings.proxy_url:
        return True, settings.proxy_type or "http", []
    try:
        from pry.engine.proxy_manager import ProxyManager

        manager = ProxyManager()
        if manager.get_proxy_url() and manager.active_config.provider != "free":
            return True, manager.active_config.provider, []
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError) as exc:
        # The probe is best-effort: a broken/unreachable proxy store must not
        # fail capability detection, it just reports "no proxy" + a hint.
        logger.debug("proxy manager probe failed: %s", exc, exc_info=True)
    return False, "none", ["set PRY_PROXY_ENABLED=true and PRY_PROXY_URL to route through a proxy"]


def _captcha_capability() -> tuple[bool, str, list[str]]:
    """Detect the free CAPTCHA engines (OCR, ASR, puzzle CV, browser integrity).

    Paid token services are retired by policy: no key is read and none is
    recommended. An absent engine is a typed refusal, not an upsell.
    """
    recs: list[str] = []
    engines: list[str] = []
    ocr_pkg = probes._module_import_state(probes.MOD_PYTESSERACT) == "ok"
    ocr_bin = probes.shutil.which("tesseract") is not None
    if ocr_pkg and ocr_bin:
        engines.append("local OCR (pytesseract + tesseract)")
    for module, label in (
        ("ddddocr", "local OCR (ddddocr)"),
        ("faster_whisper", "audio ASR (faster-whisper)"),
        ("cv2", "puzzle CV (opencv)"),
        ("patchright", "browser integrity (patchright)"),
    ):
        if probes._module_import_state(module) == "ok":
            engines.append(label)
    if not engines:
        recs.append("pip install 'pryscraper[captcha]' (ddddocr + faster-whisper), or apt-get install tesseract-ocr for the legacy OCR path")
    return bool(engines), "; ".join(engines) or "no free CAPTCHA engine installed", recs


def _llm_capability() -> tuple[bool, str, list[str]]:
    """Detect whether an LLM API key is configured (booleans/provider names only)."""
    providers = [
        name
        for name, key in (
            ("openrouter", settings.openrouter_api_key),
            ("openai", settings.openai_api_key),
            ("anthropic", settings.anthropic_api_key),
            ("cohere", settings.cohere_api_key),
        )
        if key
    ]
    if providers:
        return True, ", ".join(providers), []
    return (
        False,
        "no LLM API key configured",
        [
            "set PRY_OPENROUTER_API_KEY (or PRY_OPENAI_API_KEY / PRY_ANTHROPIC_API_KEY / "
            "PRY_COHERE_API_KEY) to enable LLM features"
        ],
    )
