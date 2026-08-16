"""Pry — shared token-provider HTTP logic (2captcha-style + Capsolver).

Implements the standard create-task -> poll-result loops used by the
``recaptcha_v2``, ``recaptcha_v3``, ``hcaptcha`` and ``turnstile``
providers. No API key is hardcoded here — callers pass the key from
settings, and every helper returns ``None`` instead of raising when the
upstream API rejects the request or times out.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TWO_CAPTCHA_CREATE_URL = "https://2captcha.com/in.php"
TWO_CAPTCHA_RESULT_URL = "https://2captcha.com/res.php"
CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


def _new_client() -> httpx.AsyncClient:
    """Create a short-lived client for a single solve/poll exchange."""
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)


async def solve_2captcha(
    api_key: str,
    method: str,
    *,
    sitekey: str,
    url: str,
    extra: dict[str, Any] | None = None,
    poll_interval: float = 3.0,
    max_polls: int = 30,
) -> str | None:
    """Solve a token CAPTCHA via a 2captcha-compatible API.

    ``method`` is the 2captcha method name (e.g. ``userrecaptcha``,
    ``recaptcha_v3``, ``hcaptcha``, ``turnstile``). Returns the solution
    token or None on any failure.
    """
    if not api_key or not sitekey or not url:
        return None
    params: dict[str, Any] = {
        "key": api_key,
        "method": method,
        "googlekey": sitekey,
        "pageurl": url,
        "json": 1,
    }
    if extra:
        params.update(extra)
    try:
        async with _new_client() as client:
            resp = await client.post(TWO_CAPTCHA_CREATE_URL, data=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 1:
                logger.warning("2captcha create failed: %s", data.get("request"))
                return None
            task_id = str(data["request"])
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                poll = await client.get(
                    TWO_CAPTCHA_RESULT_URL,
                    params={"key": api_key, "action": "get", "id": task_id, "json": 1},
                )
                poll.raise_for_status()
                result = poll.json()
                if result.get("status") == 1:
                    return str(result.get("request", "")) or None
                request = str(result.get("request", ""))
                if request and "CAPCHA_NOT_READY" not in request:
                    logger.warning("2captcha task failed: %s", request)
                    return None
            logger.warning("2captcha poll timed out for task %s", task_id)
            return None
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("2captcha error: %s", exc)
        return None


async def solve_capsolver(
    api_key: str,
    task_type: str,
    *,
    sitekey: str,
    url: str,
    extra: dict[str, Any] | None = None,
    poll_interval: float = 2.0,
    max_polls: int = 40,
) -> str | None:
    """Solve a token CAPTCHA via Capsolver.

    ``task_type`` is the Capsolver task type (e.g. ``ReCaptchaV2Task``,
    ``ReCaptchaV3Task``, ``HCaptchaTask``, ``TurnstileTask``). Returns the
    solution token or None on any failure.
    """
    if not api_key or not sitekey or not url:
        return None
    task: dict[str, Any] = {
        "type": task_type,
        "websiteKey": sitekey,
        "websiteURL": url,
    }
    if extra:
        task.update(extra)
    try:
        async with _new_client() as client:
            resp = await client.post(
                CAPSOLVER_CREATE_URL, json={"clientKey": api_key, "task": task}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errorId", 0) != 0:
                logger.warning("capsolver create failed: %s", data.get("errorDescription"))
                return None
            task_id = data.get("taskId")
            if not task_id:
                return None
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                poll = await client.post(
                    CAPSOLVER_RESULT_URL,
                    json={"clientKey": api_key, "taskId": task_id},
                )
                poll.raise_for_status()
                result = poll.json()
                if result.get("status") == "ready":
                    solution = result.get("solution") or {}
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    return str(token) if token else None
                if result.get("errorId", 0) != 0:
                    logger.warning("capsolver task failed: %s", result.get("errorDescription"))
                    return None
            logger.warning("capsolver poll timed out for task %s", task_id)
            return None
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("capsolver error: %s", exc)
        return None
