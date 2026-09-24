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
    except Exception:  # noqa: BLE001 - capability probes fail closed
        logger.debug("proxy manager probe failed", exc_info=True)
    return False, "none", ["set PRY_PROXY_ENABLED=true and PRY_PROXY_URL to route through a proxy"]


def _captcha_capability() -> tuple[bool, str, list[str]]:
    """Detect CAPTCHA solving backends (OCR and/or paid token APIs).

    API keys contribute booleans only — values are never exposed.
    """
    recs: list[str] = []
    ocr_pkg = probes._module_import_state(probes.MOD_PYTESSERACT) == "ok"
    ocr_bin = probes.shutil.which("tesseract") is not None
    ocr_ready = ocr_pkg and ocr_bin

    api_keys = [
        name
        for name, key in (
            ("2captcha", settings.captcha_2captcha_api_key),
            ("capsolver", settings.captcha_capsolver_api_key),
        )
        if key
    ]

    parts: list[str] = []
    if ocr_ready:
        parts.append("local OCR (pytesseract + tesseract)")
    elif ocr_pkg or ocr_bin:
        parts.append("incomplete OCR: pytesseract and the tesseract binary are both required")
        if ocr_pkg and not ocr_bin:
            recs.append("install the tesseract binary (apt-get install tesseract-ocr)")
        else:
            recs.append("pip install pytesseract")
    else:
        recs.append("install tesseract-ocr and pip install pytesseract for local OCR")

    if api_keys:
        parts.append("API keys: " + ", ".join(api_keys))
    else:
        recs.append(
            "set PRY_CAPTCHA_2CAPTCHA_API_KEY or PRY_CAPTCHA_CAPSOLVER_API_KEY "
            "for paid CAPTCHA solving"
        )

    return ocr_ready or bool(api_keys), "; ".join(parts), recs


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
