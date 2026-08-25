"""Pry — multi-provider CAPTCHA solver package.

Importing this package registers every provider in
:data:`captcha.registry.REGISTRY`:

* ``image`` — local OCR (pytesseract / EasyOCR, no network)
* ``recaptcha_v2`` / ``recaptcha_v3`` / ``hcaptcha`` / ``turnstile`` —
  token providers backed by 2captcha-style APIs or Capsolver
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# Importing the provider modules has the side effect of registering them.
from pry.engine.captcha import (  # noqa: F401
    hcaptcha,
    image_ocr,
    recaptcha_v2,
    recaptcha_v3,
    turnstile,
)
from pry.engine.captcha.base import CaptchaProvider
from pry.engine.captcha.registry import REGISTRY, get_provider, register

__all__ = [
    "REGISTRY",
    "CaptchaProvider",
    "get_provider",
    "register",
]
