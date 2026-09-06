"""Pry — payment / provider-credential settings (split from settings.py).

Mixin holding all BYOK LLM provider keys, CAPTCHA solver credentials, and
sports-data API keys. Combined into `PrySettings` in `pry.core.settings`.

Pure code move — no config values or logic changed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations


class PaymentsSettings:
    """LLM provider keys, CAPTCHA credentials, and sports-data API keys."""

    # LLM providers — BYOK (bring your own key).
    # Consumers set these (PRY_<NAME>_API_KEY env, or the provider's standard
    # env var) to enable each AI feature. One account per provider; multi-key
    # fan-out is a deployment concern, not a product setting.
    ollama_url: str = "http://localhost:11434"
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    kilocode_api_key: str = ""
    kilocode_base_url: str = ""  # set KILOCODE_BASE_URL to your gateway
    kimi_api_key: str = ""
    nvidia_api_key: str = ""
    nous_api_key: str = ""
    zai_api_key: str = ""
    cerebras_api_key: str = ""
    minimax_api_key: str = ""
    siliconflow_api_key: str = ""
    opencode_zen_api_key: str = ""

    # CAPTCHA solving (see captcha_solver.py + captcha/ package)
    # 2captcha-style API key (also used by anti-captcha.com / capmonster clones)
    captcha_2captcha_api_key: str = ""
    # Capsolver API key (https://www.capsolver.com)
    captcha_capsolver_api_key: str = ""
    # OCR backend for image captchas: "tesseract" (pytesseract) | "easyocr" | "auto"
    captcha_ocr_backend: str = "tesseract"
    # DeathByCaptcha credentials (https://www.deathbycaptcha.com)
    captcha_deathbycaptcha_username: str = ""
    captcha_deathbycaptcha_password: str = ""
    # NextCaptcha API key (https://nextcaptcha.com)
    captcha_nextcaptcha_api_key: str = ""

    # Sports data (sports_data/ package) — The Odds API
    # Live odds key (https://the-odds-api.com). Free tier: 500
    # requests/month. Without a key the sports_data modules degrade to ESPN
    # public scoreboards. Also resolved via the secrets backend under the
    # name "odds_api_key" (see _apply_secrets_backend).
    odds_api_key: str = ""
