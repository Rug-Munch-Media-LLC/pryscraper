"""Hidden-API discovery tier — scan HTML/JS for the JSON endpoints the frontend calls."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re

from pry.engine.methods._common import _resolve_candidate

_SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FETCH_RE = re.compile(r"""fetch\s*\(\s*["']([^"']+)["']""")
_AXIOS_CALL_RE = re.compile(r"""axios(?:\.\w+)?\s*\(\s*["']([^"']+)["']""")
_AXIOS_OBJ_RE = re.compile(r"""axios\s*\(\s*\{[^}]*?url\s*:\s*["']([^"']+)["']""")
_XHR_RE = re.compile(r"""XMLHttpRequest\.open\s*\(\s*["'][^"']+["']\s*,\s*["']([^"']+)["']""")
_JQUERY_RE = re.compile(r"""\$\s*\.\s*(?:ajax|get|post|getJSON)\s*\(\s*["']([^"']+)["']""")
_API_PATH_RE = re.compile(r"""["']([^"']*/api/[^"']*)["']""", re.IGNORECASE)
_JSON_SUFFIX_RE = re.compile(r"""["']([^"']*\.json(?:[?#][^"']*)?)["']""", re.IGNORECASE)


def discover_json_api(page_url: str, html: str) -> list[str]:
    """Discover hidden JSON API endpoints from a page's HTML.

    Parses (a) inline ``fetch()`` / ``axios()`` / XHR / jQuery API calls,
    (b) quoted ``/api/...`` and ``.json`` path references, and (c) the JS
    bundle URLs referenced by ``<script src>`` — fetching and re-scanning
    those bundles surfaces the endpoints hidden inside them. All relative
    references are resolved against ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from (used to resolve
            relative references).
        html: Raw page HTML (or an inline ``<script>`` body / JS bundle).

    Returns:
        De-duplicated, absolute candidate URLs, ordered by discovery
        (inline API calls first, then ``/api/`` / ``.json`` strings, then
        script bundles). Never raises: returns ``[]`` for unusable input.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return []
    page_url = page_url.strip()
    if not page_url or not html:
        return []

    raw_refs: list[str] = []
    for pattern in (
        _FETCH_RE,
        _AXIOS_CALL_RE,
        _AXIOS_OBJ_RE,
        _XHR_RE,
        _JQUERY_RE,
        _API_PATH_RE,
        _JSON_SUFFIX_RE,
    ):
        for match in pattern.finditer(html):
            if match.lastindex is None:
                continue
            raw_refs.append(match.group(1))
    # JS bundle URLs referenced by the page — scanning these surfaces the
    # endpoints hidden inside the bundles.
    raw_refs.extend(_SCRIPT_SRC_RE.findall(html))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in raw_refs:
        resolved = _resolve_candidate(raw, page_url)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        urls.append(resolved)
    return urls


__all__ = ["discover_json_api"]
