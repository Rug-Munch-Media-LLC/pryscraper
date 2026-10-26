"""Pry — submit a solved CAPTCHA token back to the page.

A solved token is worthless until it is posted: the token is sent as a form
field (``g-recaptcha-response`` by default) to the page URL, optionally with the
page's extra hidden fields.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_FIELD = "g-recaptcha-response"


async def submit_solution(
    url: str,
    token: str,
    *,
    field: str = DEFAULT_FIELD,
    extra: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> bool:
    """POST ``token`` to ``url`` as ``field`` (plus ``extra``); True on 2xx."""
    if not token:
        return False
    data: dict[str, str] = {field: token}
    data.update(extra or {})
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.post(url, data=data)
    except httpx.HTTPError as exc:
        logger.warning("captcha_submit_failed url=%s error=%s", url, exc)
        return False
    logger.info("captcha_submit url=%s field=%s status=%d", url, field, resp.status_code)
    return resp.is_success
