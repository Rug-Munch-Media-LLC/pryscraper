"""Helpers backing ``POST /v1/suggest``.

Split from ``analysis.py`` to keep it under the 200-line structure cap. Same
shape as ``_watch_webhook.py``, which was split out for the same reason.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from pry.api.client import get_client
from pry.core.settings import settings
from pry.engine.fetch_guard import guard_get

logger = logging.getLogger(__name__)


async def _fetch_page_html(url: str) -> tuple[str, str | None]:
    """Fetch a page's raw HTML through the SSRF guard.

    Returns ``(html, error)``.

    Raises:
        InvalidRequestError: Propagated from the guard when the URL (or a
            redirect it returns) is internal. The route must NOT swallow this
            into the error string: the guard's exception is a ``PryError`` with
            ``status_code`` 400, so letting it propagate is what turns a blocked
            URL into a 4xx instead of a 500.
    """
    try:
        client = await get_client()
        resp = await guard_get(client, url, timeout=15)
    except httpx.HTTPError as e:
        # Transport-only failure: the URL was safe, the host was not reachable.
        error = f"{type(e).__name__}: {e}"[:300]
        logger.warning("suggest_schema_fetch_failed", extra={"url": url, "error": error})
        return "", error
    return resp.text, None


async def _add_llm_suggestions(schema: dict[str, Any], content: str) -> None:
    """Merge the local model's selector suggestions into ``schema`` in place."""
    try:
        client = await get_client()
        resp = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": "qwen2.5-coder:3b",
                "prompt": (
                    "Analyze this page. Return ONLY JSON with field names as keys and"
                    " CSS selectors as values. Look for: price, name, description,"
                    " image, rating, stock.\n\n" + content[:4000]
                ),
                "stream": False,
                "options": {"num_ctx": 8192, "temperature": 0.1},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return
        m = re.search(r"\{.*\}", resp.json().get("response", ""), re.S)
        if not m:
            return
        try:
            llm = json.loads(m.group(0))
        except json.JSONDecodeError:
            logger.warning("llm_schema_parse_failed")
            return
        if isinstance(llm, dict):
            schema["llm_suggested"] = llm
    except httpx.HTTPError:
        # settings.ollama_url is server configuration, not caller input.
        logger.warning("ollama_suggest_schema_failed")


# The watch-webhook delivery path (SSRF-guarded fire-and-forget POST plus the
# done-callback that makes its outcome observable) lives in
# pry.api.routers.ai._watch_webhook. It is re-exported here because these are the
# names analysis.py has always exposed -- callers and the regression tests bind
# to them on THIS module (the scheduler test swaps ``_fire_watch_webhook`` out on
# this module), and the scheduler looks ``_fire_watch_webhook`` up here at call
# time, so the binding must stay a real attribute of this module.
from pry.api.routers.ai._watch_webhook import (  # noqa: E402,F401 -- public re-export
    _fire_watch_webhook,
    _log_watch_webhook_outcome,
    _schedule_watch_webhook,
)
