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
DEATHBYCAPTCHA_LOGIN_URL = "https://api.deathbycaptcha.com/api/login"
DEATHBYCAPTCHA_CREATE_URL = "https://api.deathbycaptcha.com/api/captcha"
NEXTCAPTCHA_CREATE_URL = "https://api.nextcaptcha.com/v1/createTask"
NEXTCAPTCHA_RESULT_URL = "https://api.nextcaptcha.com/v1/getTaskResult"

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


async def solve_deathbycaptcha(
    username: str,
    password: str,
    *,
    sitekey: str,
    url: str,
    proxy: str | None = None,
    proxy_type: str = "HTTP",
) -> str | None:
    """Solve a reCAPTCHA v2 via DeathByCaptcha.

    Uses the DeathByCaptcha API (username/password auth). Returns the
    solution token or None on any failure.
    """
    if not username or not password or not sitekey or not url:
        return None
    try:
        async with _new_client() as client:
            payload = {
                "username": username,
                "password": password,
                "type": 4,  # reCAPTCHA v2
                "googlekey": sitekey,
                "pageurl": url,
            }
            if proxy:
                payload["proxy"] = proxy
                payload["proxytype"] = proxy_type
            resp = await client.post(DEATHBYCAPTCHA_CREATE_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == 0:
                logger.warning("deathbycaptcha failed: %s", data.get("error", "unknown"))
                return None
            return str(data.get("text", "")) or None
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("deathbycaptcha error: %s", exc)
        return None


async def solve_nextcaptcha(
    api_key: str,
    task_type: str,
    *,
    sitekey: str,
    url: str,
    extra: dict[str, Any] | None = None,
    poll_interval: float = 5.0,
    max_polls: int = 20,
) -> str | None:
    """Solve a token CAPTCHA via NextCaptcha (OpenAI-compatible API).

    ``task_type`` is the NextCaptcha task type. Returns the solution token
    or None on any failure.
    """
    if not api_key or not sitekey or not url:
        return None
    task: dict[str, Any] = {
        "type": task_type,
        "websiteURL": url,
        "websiteKey": sitekey,
    }
    if extra:
        task.update(extra)
    try:
        async with _new_client() as client:
            resp = await client.post(
                NEXTCAPTCHA_CREATE_URL,
                json={"clientKey": api_key, "task": task},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errorId", 0) != 0:
                logger.warning("nextcaptcha create failed: %s", data.get("errorDescription"))
                return None
            task_id = data.get("taskId")
            if not task_id:
                return None
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                poll = await client.post(
                    NEXTCAPTCHA_RESULT_URL,
                    json={"clientKey": api_key, "taskId": task_id},
                )
                poll.raise_for_status()
                result = poll.json()
                if result.get("status") == "ready":
                    solution = result.get("solution") or {}
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    return str(token) if token else None
                if result.get("errorId", 0) != 0:
                    logger.warning("nextcaptcha task failed: %s", result.get("errorDescription"))
                    return None
            logger.warning("nextcaptcha poll timed out for task %s", task_id)
            return None
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("nextcaptcha error: %s", exc)
        return None


# Fallback chain: try each provider in order, return first success
SOLVER_FALLBACK_CHAIN: list[str] = [
    "2captcha",  # 2captcha-style API (free tier available)
    "capsolver",  # Capsolver (second provider)
    "deathbycaptcha",  # DeathByCaptcha (username/password auth)
    "nextcaptcha",  # NextCaptcha (OpenAI-compatible)
]


async def solve_token_with_fallback(
    captcha_type: str,
    *,
    sitekey: str,
    url: str,
    extra: dict[str, Any] | None = None,
    captcha_action: str = "",
    min_score: float = 0.3,
) -> str | None:
    """Solve a token CAPTCHA using the full fallback chain.

    Tries each provider in SOLVER_FALLBACK_CHAIN order. Returns the first
    successful token or None if all providers fail.
    """
    from settings import settings

    method_map = {
        "recaptcha_v2": ("userrecaptcha", "ReCaptchaV2Task", "ReCaptchaV2Task"),
        "recaptcha_v3": ("recaptcha_v3", "ReCaptchaV3Task", "ReCaptchaV3Task"),
        "hcaptcha": ("hcaptcha", "HCaptchaTask", "HCaptchaTask"),
        "turnstile": ("turnstile", "TurnstileTask", "TurnstileTask"),
    }
    mapping = method_map.get(captcha_type)
    if not mapping:
        return None

    method_2captcha, method_capsolver, method_nextcaptcha = mapping
    task_extra = dict(extra or {})
    if captcha_action and captcha_type == "recaptcha_v3":
        task_extra["action"] = captcha_action
    if min_score and captcha_type == "recaptcha_v3":
        task_extra["min_score"] = min_score

    for solver in SOLVER_FALLBACK_CHAIN:
        token: str | None = None
        if solver == "2captcha" and settings.captcha_2captcha_api_key:
            token = await solve_2captcha(
                settings.captcha_2captcha_api_key,
                method_2captcha,
                sitekey=sitekey,
                url=url,
                extra=task_extra,
            )
        elif solver == "capsolver" and settings.captcha_capsolver_api_key:
            token = await solve_capsolver(
                settings.captcha_capsolver_api_key,
                method_capsolver,
                sitekey=sitekey,
                url=url,
                extra=task_extra,
            )
        elif solver == "deathbycaptcha":
            dbc_user = settings.captcha_deathbycaptcha_username or ""
            dbc_pass = settings.captcha_deathbycaptcha_password or ""
            if dbc_user and dbc_pass:
                token = await solve_deathbycaptcha(
                    dbc_user,
                    dbc_pass,
                    sitekey=sitekey,
                    url=url,
                )
        elif solver == "nextcaptcha" and settings.captcha_nextcaptcha_api_key:
            token = await solve_nextcaptcha(
                settings.captcha_nextcaptcha_api_key,
                method_nextcaptcha,
                sitekey=sitekey,
                url=url,
                extra=task_extra,
            )
        if token:
            return token
    return None
