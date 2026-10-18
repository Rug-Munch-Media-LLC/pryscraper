"""Pry — Firecrawl-compatible media formats for ``POST /v1/scrape``.

``formats: ["screenshot"]`` and ``formats: ["pdf"]`` are rendered by the
engine browser hook (``UltimateScraper.render_media``), which reuses the
process-wide ``BrowserPool``. The route passes that callable in, so this
module only encodes the bytes, enforces the size caps and maps failures onto
``ScrapeError`` — no second browser path lives here.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any

from pry.core.errors import ScrapeError

MEDIA_FORMATS = frozenset({"screenshot", "pdf"})
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
DEFAULT_RENDER_TIMEOUT_S = 30
MAX_RENDER_TIMEOUT_S = 60

RenderMedia = Callable[..., Awaitable[dict[str, Any]]]


def _capped(name: str, raw: bytes, cap: int) -> str:
    """Base64-encode ``raw`` after the empty/oversize checks."""
    if not raw:
        raise ScrapeError(f"{name} render returned no data")
    if len(raw) > cap:
        raise ScrapeError(f"{name} is {len(raw)} bytes, over the {cap} byte cap")
    return base64.b64encode(raw).decode()


async def media_extras(
    requested: set[str],
    url: str,
    renderer: RenderMedia | None,
    budget_s: int | None = DEFAULT_RENDER_TIMEOUT_S,
) -> dict[str, Any]:
    """Return ``screenshot``/``pdf`` base64 extras, or ``{}`` when unused."""
    wanted = requested & MEDIA_FORMATS
    if not wanted:
        return {}
    if renderer is None:  # pragma: no cover - engine always provides the hook
        raise ScrapeError("media formats require a browser renderer")
    budget = min(int(budget_s or DEFAULT_RENDER_TIMEOUT_S), MAX_RENDER_TIMEOUT_S)
    try:
        rendered = await renderer(
            url,
            want_screenshot="screenshot" in wanted,
            want_pdf="pdf" in wanted,
            timeout_s=budget,
        )
    except ScrapeError:
        raise
    except Exception as e:
        raise ScrapeError(f"media render failed: {e}") from e
    extras: dict[str, Any] = {}
    if "screenshot" in wanted:
        extras["screenshot"] = _capped(
            "screenshot", rendered.get("screenshot") or b"", MAX_SCREENSHOT_BYTES
        )
    if "pdf" in wanted:
        extras["pdf"] = _capped("pdf", rendered.get("pdf") or b"", MAX_PDF_BYTES)
    return extras
