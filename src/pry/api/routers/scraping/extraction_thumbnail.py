# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Thumbnail extraction implementation layer.

Split out of ``extraction`` (the thin entrypoint re-exports
``extract_thumbnail``) so the router file holds route wiring only. The route
parses one page's ``<meta>``/``<img>`` tags and returns a single image URL —
it shares no helper with the table/links/SEO/email routes, so it has no reason
to sit in the same module.

``extraction`` owns the shared ``scraper``/``get_client``/``guard_get`` names.
They are read back through the entrypoint at CALL time rather than bound
locally, so a test patching ``extraction.scraper`` (or ``extraction.guard_get``)
keeps working — module-attribute monkeypatching stays effective instead of being
frozen into locals at import time. This mirrors ``extraction_llm`` exactly; no
back-reference is wired up by the entrypoint, so this module also imports
cleanly on its own.
"""

from __future__ import annotations

import re
from importlib import import_module
from typing import TYPE_CHECKING, Any

from fastapi import Body

if TYPE_CHECKING:
    from types import ModuleType


def _owner() -> ModuleType:
    """Return the thin entrypoint that owns the shared router names.

    Resolved at call time so this layer never binds a local copy of ``scraper``
    at import time — patching the entrypoint stays effective.
    """
    return import_module(f"{__name__.rsplit('.', 1)[0]}.extraction")


async def extract_thumbnail(url: str = Body(...)) -> dict[str, Any]:
    """Extract the og:image, twitter:image, or first img src from a page.
    Uses Cloudflare bypass when needed. Returns the thumbnail URL or None."""
    owner = _owner()
    try:
        result = await owner.scraper.scrape(url, {"bypass_cloudflare": True})
        html = result.get("raw_html", "")
        if not html:
            client = await owner.get_client()
            resp = await owner.guard_get(client, url)
            html = resp.text
    except Exception:  # noqa: BLE001 — thumbnail is best-effort; any failure yields None
        # ``{"thumbnail": None}`` is the SAME payload a page with no og:image /
        # twitter:image / img tag returns, so a transport or parse failure would
        # be reported as "this page has no thumbnail" — a fabricated result.
        # Signal the failure explicitly instead.
        return {
            "success": False,
            "error": "thumbnail extraction failed",
            "data": {"thumbnail": None},
        }

    # Try og:image first
    og = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.I)
    if og:
        return {"success": True, "data": {"thumbnail": og.group(1), "source": "og:image"}}

    # Try twitter:image
    tw = re.search(r'<meta\s+name="twitter:image"\s+content="([^"]+)"', html, re.I)
    if tw:
        return {"success": True, "data": {"thumbnail": tw.group(1), "source": "twitter:image"}}

    # Try twitter:image:src
    tws = re.search(r'<meta\s+name="twitter:image:src"\s+content="([^"]+)"', html, re.I)
    if tws:
        return {"success": True, "data": {"thumbnail": tws.group(1), "source": "twitter:image:src"}}

    # Try first img tag
    img = re.search(r'<img\s[^>]*src="([^"]+)"', html, re.I)
    if img:
        src = img.group(1)
        if src.startswith("/"):
            from urllib.parse import urljoin

            src = urljoin(url, src)
        return {"success": True, "data": {"thumbnail": src, "source": "first-img"}}

    return {"success": True, "data": {"thumbnail": None}}
