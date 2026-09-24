"""Pry — Qwant search engine.

The HTML app is JS-hydrated behind obfuscated class names, so its JSON API
is used instead. That API rejects requests without ``tgp=3``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_QWANT_API = "https://api.qwant.com/v3/search/web?q={q}&count=10&locale=en_US&safesearch=1&tgp=3"


async def search_qwant(query: str, num_results: int) -> list[dict[str, Any]]:
    """Qwant via its JSON API (the HTML app is JS-hydrated and yields no anchors)."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Referer": "https://www.qwant.com/",
            },
        ) as client:
            resp = await client.get(_QWANT_API.format(q=quote_plus(query)))
            resp.raise_for_status()
            payload = resp.json()
        out: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if len(out) >= num_results:
                return
            if isinstance(node, dict):
                if node.get("url") and node.get("title"):
                    out.append(
                        {
                            "url": node["url"],
                            "title": str(node["title"])[:200],
                            "snippet": str(node.get("desc") or node.get("description") or ""),
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return out[:num_results]
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("qwant_search_failed", extra={"error": str(exc)})
        return []


__all__ = ["search_qwant"]


__all__ = ["search_qwant"]
