"""mail.tm temporary-mail verification fallback."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from pry.commerce.signup.email_verification.common import extract_verification_link

_TEMP_MAIL_DOMAINS: frozenset[str] = frozenset({"mail.tm", "inbox.tm"})


def _mail_tm_api_base() -> str:
    return os.environ.get("SIGNUP_MAIL_TM_API", "https://api.mail.tm").rstrip("/")


def _looks_like_temp_mail(email: str) -> bool:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    env_domains = os.environ.get("SIGNUP_MAIL_TM_DOMAINS", "")
    extras = {d.strip().lower() for d in env_domains.split(",") if d.strip()}
    return domain in _TEMP_MAIL_DOMAINS or domain in extras


async def _mail_tm_token(
    client: httpx.AsyncClient, base: str, email: str, password: str | None
) -> str | None:
    if not password:
        return None
    resp = await client.post(f"{base}/token", json={"address": email, "password": password})
    if resp.status_code == 200:
        data = resp.json()
        token = data.get("token") if isinstance(data, dict) else None
        return str(token) if token else None
    return None


async def _mail_tm_create_account(
    client: httpx.AsyncClient, base: str, email: str, password: str
) -> str | None:
    resp = await client.post(f"{base}/accounts", json={"address": email, "password": password})
    if resp.status_code not in (200, 201):
        return None
    return await _mail_tm_token(client, base, email, password)


async def fetch_temp_mail(
    email: str,
    password: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Poll a mail.tm inbox for a verification link/code.

    If ``password`` is provided the account is authenticated; otherwise an
    account is created for ``email`` (works for ``@mail.tm``-style addresses).
    """
    base = _mail_tm_api_base()
    owns_client = client is None
    ac = client if client is not None else httpx.AsyncClient(follow_redirects=True, timeout=30.0)
    try:
        token = await _mail_tm_token(ac, base, email, password)
        if token is None:
            if password is None:
                return {
                    "success": False,
                    "verified": False,
                    "method": "mail_tm",
                    "error": "cannot create a mail.tm account without a password",
                    "link": None,
                    "code": None,
                }
            token = await _mail_tm_create_account(ac, base, email, password)
            if token is None:
                return {
                    "success": False,
                    "verified": False,
                    "method": "mail_tm",
                    "error": "mail.tm account creation/authentication failed",
                    "link": None,
                    "code": None,
                }

        headers = {"Authorization": f"Bearer {token}"}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            resp = await ac.get(f"{base}/messages", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                messages = data if isinstance(data, list) else []
                if messages:
                    first = messages[0]
                    if isinstance(first, dict) and first.get("id"):
                        detail_resp = await ac.get(
                            f"{base}/messages/{first['id']}", headers=headers
                        )
                        if detail_resp.status_code == 200:
                            payload = detail_resp.json()
                            if isinstance(payload, dict):
                                body = (
                                    payload.get("text")
                                    or "\n".join(payload.get("html", []) or [])
                                    or payload.get("intro")
                                    or ""
                                )
                                link, code = extract_verification_link(body)
                                if link or code:
                                    return {
                                        "success": True,
                                        "verified": True,
                                        "method": "mail_tm",
                                        "link": link,
                                        "code": code,
                                        "subject": first.get("subject"),
                                    }
            await asyncio.sleep(2.0)

        return {
            "success": True,
            "verified": False,
            "method": "mail_tm",
            "error": "timeout waiting for messages",
            "link": None,
            "code": None,
        }
    except httpx.HTTPError as exc:
        return {
            "success": False,
            "verified": False,
            "method": "mail_tm",
            "error": f"mail.tm request failed: {exc}",
            "link": None,
            "code": None,
        }
    finally:
        if owns_client:
            await ac.aclose()
