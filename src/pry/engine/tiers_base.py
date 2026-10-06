"""Shared helpers for the tier implementations (TierMixin base).

Holds the non-tier methods every ``_tier_*`` strategy relies on: header
building, content validation, text extraction, block-signal detection and
fallback telemetry. The concrete tiers live in ``tiers_http``,
``tiers_browser`` and ``tiers_special``; ``tiers.py`` composes them into
``TierMixin``.

Availability flags (``_has_cloudscraper`` etc.) remain module-level globals
on ``pry.engine.ultimate_scraper`` because tests patch them there; tier
methods resolve them lazily through :func:`_us_flag` so patches stay
effective.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import random
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    import httpx

_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)


def _us_flag(name: str) -> Any:
    """Read an availability flag / scraper object from ultimate_scraper.

    Lazy module lookup (never at import time) avoids a circular import while
    keeping ``patch("pry.engine.ultimate_scraper._has_x", ...)`` effective.
    """
    from pry.engine import ultimate_scraper as _us

    return getattr(_us, name)


async def _get_shared_client() -> httpx.AsyncClient:
    """Lazy import to avoid engine→api boundary violation (import-linter)."""
    from pry.core.client import get_client

    return await get_client()


class TierBase:
    """Shared helpers mixed into :class:`UltimateScraper` alongside the tiers."""

    def _rotate_ua(self) -> str:
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _build_headers(self, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": _RNG.choice(["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7"]),
            "Referer": f"https://{parsed.netloc}/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    def _is_valid(self, html: str | None) -> bool:
        if not html or len(html) < 500:
            return False
        lower = html.lower()
        block_indicators = [
            "cloudflare",
            "attention required",
            "just a moment",
            "enable javascript",
            "verify you are human",
        ]
        if any(i in lower for i in block_indicators) and len(html) < 5000:
            return False
        body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        if body:
            text = re.sub(r"<[^>]+>", " ", body.group(1)).strip()
            if len(text) < 50:
                return False
        return True

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        try:
            from trafilatura import extract

            content = extract(
                html, output_format="markdown", include_links=True, include_images=False
            )
            if content and len(content) > 100:
                return content
        except Exception:
            logger.warning("silent_exception_swallowed", exc_info=True)
        try:
            from readability import Document

            doc = Document(html)
            content = doc.summary()
            if content and len(content) > 100:
                from markdownify import markdownify

                return markdownify(content, heading_arrows=False, strip=["script", "style"])  # type: ignore[call-arg]  # markdownify supports heading_arrows at runtime
        except Exception:
            logger.warning("silent_exception_swallowed", exc_info=True)
        # Last resort: strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:50000] if len(text) > 50000 else text

    @staticmethod
    def _signal_to_dict(signal: Any) -> dict[str, Any]:
        """Convert a BlockSignal dataclass into a JSON-safe dict."""
        return {
            "kind": signal.kind,
            "confidence": signal.confidence,
            "recommended_escalation": signal.recommended_escalation,
            "evidence": list(signal.evidence),
        }

    def _detect_block_signal(self, html: str | None) -> Any:
        """Run block detection on a tier response; ``None`` when unavailable.

        Tiers expose only the body, so status/headers default to ``200``/``{}``
        and body markers drive the classification. A failed tier (``html is
        None``) yields an empty-body ``none`` signal — harmless, and it keeps
        the detect-on-every-attempt contract explicit.
        """
        if not _us_flag("_HAS_BLOCK_DETECTION"):
            return None
        block_detect = _us_flag("_block_detect")
        if html is not None:
            return block_detect(html, 200, {})
        return block_detect("", 0, {})

    def _record_telemetry(
        self,
        domain: str,
        tier_order: list[str],
        attempts: list[dict[str, Any]],
        final_tier: str | None,
        success: bool,
        start: float,
        errors: list[str],
    ) -> None:
        """Record the fallback journey via fallback_telemetry (best-effort).

        Never raises: telemetry is observability, not a correctness path.
        """
        if not _us_flag("_HAS_FALLBACK_TELEMETRY"):
            return
        try:
            _us_flag("_record_fallback")(
                domain=domain,
                tier_order=tier_order,
                attempts=attempts,
                final_tier=final_tier,
                success=success,
                duration_ms=round((time.time() - start) * 1000, 2),
                error="; ".join(errors[-5:]) if (errors and not success) else None,
            )
        except Exception:
            logger.debug("fallback_telemetry_record_failed", exc_info=True)
