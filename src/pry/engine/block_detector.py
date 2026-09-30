"""Pry — anti-bot block detection for a fetched response.

Analyses HTML, status code and response headers to decide whether a page is
an anti-bot interstitial rather than real content, and at what confidence.

Extracted from ``pry.engine.scraper`` where the class lived beside the
scraper that consumes it; it is a pure analysis of one response and is
imported independently by the scraping routers. The historical import path
``from pry.engine.scraper import BlockDetector`` still resolves — scraper.py
re-exports this class.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import Any, ClassVar


class BlockDetector:
    """Detect anti-bot blocks by analyzing HTML, status codes, and headers."""

    VENDOR_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "cloudflare": [
            "cloudflare",
            "cf-",
            "checking your browser",
            "attention required",
            "just a moment",
            "_cf_chl_opt",
            "cdn-cgi",
        ],
        "datadome": ["datadome", "blocked because we believe"],
        "akamai": ["akamai", "akamaiedge"],
        "imperva": ["imperva", "incapsula"],
    }

    GENERIC_PATTERNS: ClassVar[list[str]] = [
        "captcha",
        "access denied",
        "blocked",
        "too many requests",
        "rate limit",
        "403 forbidden",
        "503 service unavailable",
    ]

    def __init__(self, min_content_length: int = 500):
        self.min_content_length = min_content_length

    def detect(
        self, html: str, status_code: int, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "blocked": False,
            "tier": None,
            "vendor": None,
            "confidence": 0.0,
            "reason": "",
        }
        headers = headers or {}
        lower_html = html.lower()
        server = headers.get("server", "").lower()
        cf_ray = headers.get("cf-ray", "")

        for vendor, patterns in self.VENDOR_PATTERNS.items():
            if any(re.search(p, lower_html) or re.search(p, server) for p in patterns):
                result.update(
                    {
                        "blocked": True,
                        "tier": "vendor",
                        "vendor": vendor,
                        "confidence": 0.95,
                        "reason": f"{vendor} block detected",
                    }
                )
                return result

        if status_code in (403, 503):
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "unknown",
                    "confidence": 0.8,
                    "reason": f"HTTP {status_code}",
                }
            )
            return result
        if status_code == 429:
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "rate_limit",
                    "confidence": 0.9,
                    "reason": "Rate limited",
                }
            )
            return result

        if any(re.search(p, lower_html) for p in self.GENERIC_PATTERNS):
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "unknown",
                    "confidence": 0.7,
                    "reason": "Block pattern matched",
                }
            )
            return result

        body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        body_text = re.sub(r"<[^>]+>", "", body.group(1) if body else "").strip()
        if body_text and len(body_text) < self.min_content_length:
            result.update(
                {
                    "blocked": True,
                    "tier": "structural",
                    "vendor": "empty_page",
                    "confidence": 0.4,
                    "reason": f"Body too short ({len(body_text)} chars)",
                }
            )

        if cf_ray and status_code >= 400:
            result.update(
                {
                    "blocked": True,
                    "tier": "vendor",
                    "vendor": "cloudflare",
                    "confidence": 0.85,
                    "reason": "Cloudflare challenge",
                }
            )
            return result

        return result
