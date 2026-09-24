"""Verification-path selection and confirmation-link helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from pry.commerce.signup.email_verification.common import IMAPConfig, imap_config_from_env
from pry.commerce.signup.email_verification.imap import poll_imap_for_verification
from pry.commerce.signup.email_verification.temp_mail import (
    _looks_like_temp_mail,
    fetch_temp_mail,
)

if TYPE_CHECKING:
    import httpx


async def _verify_via_imap(
    email: str, config: IMAPConfig, timeout_seconds: float
) -> dict[str, Any]:
    """Poll IMAP until a verification link/code appears or timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = await asyncio.to_thread(poll_imap_for_verification, config, from_email=email)
        if result.get("success") and (result.get("link") or result.get("code")):
            return {
                "success": True,
                "verified": True,
                "method": "imap",
                "link": result.get("link"),
                "code": result.get("code"),
            }
        if time.monotonic() >= deadline:
            return {
                "success": True,
                "verified": False,
                "method": "imap",
                "error": result.get("error") or "timeout waiting for verification email",
                "link": None,
                "code": None,
            }
        await asyncio.sleep(2.0)


async def verify_email(
    email: str,
    imap_config: IMAPConfig | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Look for the verification link/code for a freshly registered account.

    Resolution order:
        1. IMAP mailbox (explicit ``imap_config`` or ``SIGNUP_IMAP_*`` env).
        2. mail.tm fallback when the address looks like a temp-mail address.
        3. ``method="none"`` — no verification mailbox configured.

    Never raises: failures are returned inside the result dict.
    """
    config = imap_config or imap_config_from_env()
    if config is not None:
        return await _verify_via_imap(email, config, timeout_seconds=timeout_seconds)
    if _looks_like_temp_mail(email):
        return await fetch_temp_mail(email, client=client, timeout_seconds=timeout_seconds)
    return {
        "success": True,
        "verified": False,
        "method": "none",
        "reason": (
            "no verification mailbox configured "
            "(set SIGNUP_IMAP_HOST/SIGNUP_IMAP_USER/SIGNUP_IMAP_PASSWORD "
            "or use a temp-mail address)"
        ),
        "link": None,
        "code": None,
    }


async def follow_verification_link(client: httpx.AsyncClient, link: str) -> httpx.Response:
    """Follow a confirmation link with redirects enabled."""
    return await client.get(link, follow_redirects=True)
