"""Email verification helpers for the signup automation engine.

Three verification paths are supported:

1. **IMAP polling** — read a verification link/code from a mailbox using
   ``SIGNUP_IMAP_*`` environment variables (host/user/password).
2. **Temp-mail API** (mail.tm) fallback — create/authenticate a mail.tm
   account for the address being verified and poll it for messages.
3. **None** — if neither a mailbox nor a temp-mail address is configured,
   verification is skipped (the engine still reports success, just not
   ``confirmed``).

All network access goes through ``httpx`` (injectable for tests) and the
IMAP client is patchable via ``signup.email_verification.imaplib``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import imaplib
import os
import re
import time
from dataclasses import dataclass
from email.parser import BytesParser
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

import httpx

if TYPE_CHECKING:
    from email.message import Message

# ---------------------------------------------------------------------------
# Verification link/code extraction
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"https?://[^\s\"'<>()\]}]+", re.IGNORECASE)
_CONFIRM_WORDS = (
    "confirm",
    "verify",
    "verification",
    "activate",
    "activation",
    "email-verification",
)
_TRAILING_PUNCTUATION = '.,;:!?)]}"'

_CODE_PATTERNS = (
    re.compile(
        r"(?:verification\s*code|confirm\s*code|validation\s*code|one[- ]time\s*(?:code|pin)|code|pin|token)[:\s#]+([A-Za-z0-9]{4,12})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{6})\b"),
)


def _clean_link(url: str) -> str:
    return url.rstrip(_TRAILING_PUNCTUATION)


def _link_score(url: str) -> int:
    """Higher score = more likely a verification link."""
    lowered = unquote(url).lower()
    return sum(2 for word in _CONFIRM_WORDS if word in lowered)


def extract_verification_link(body: str, html: str | None = None) -> tuple[str | None, str | None]:
    """Extract ``(verification_link, verification_code)`` from email content.

    Args:
        body: Plain-text body of the email.
        html: Optional HTML body (links inside HTML are also considered).

    Returns:
        A tuple of the best-matching confirmation link (or ``None``) and a
        short verification code (or ``None``).
    """
    text = body or ""
    if html:
        # Scan raw HTML (attribute URLs survive tag stripping) AND a
        # tag-stripped view (links may be split across markup).
        stripped = re.sub(r"<[^>]+>", " ", html)
        text = f"{text}\n{html}\n{stripped}"

    links = sorted(
        {_clean_link(link) for link in _LINK_RE.findall(text)}, key=_link_score, reverse=True
    )
    link = next((url for url in links if _link_score(url) > 0), None)
    if link is None and len(links) == 1:
        link = links[0]

    code: str | None = None
    for pattern in _CODE_PATTERNS:
        match = pattern.search(text)
        if match:
            code = match.group(1)
            break

    return link, code


# ---------------------------------------------------------------------------
# IMAP configuration
# ---------------------------------------------------------------------------


@dataclass
class IMAPConfig:
    """IMAP mailbox credentials for verification polling."""

    host: str
    user: str
    password: str
    port: int = 993
    mailbox: str = "INBOX"


def imap_config_from_env() -> IMAPConfig | None:
    """Build an :class:`IMAPConfig` from ``SIGNUP_IMAP_*`` env vars.

    Returns ``None`` when ``SIGNUP_IMAP_HOST`` is not set (no IMAP path).
    """
    host = os.environ.get("SIGNUP_IMAP_HOST", "").strip()
    if not host:
        return None
    try:
        port = int(os.environ.get("SIGNUP_IMAP_PORT", "993"))
    except ValueError:
        port = 993
    return IMAPConfig(
        host=host,
        port=port,
        user=os.environ.get("SIGNUP_IMAP_USER", "").strip(),
        password=os.environ.get("SIGNUP_IMAP_PASSWORD", ""),
        mailbox=os.environ.get("SIGNUP_IMAP_MAILBOX", "INBOX").strip() or "INBOX",
    )


# ---------------------------------------------------------------------------
# IMAP polling
# ---------------------------------------------------------------------------


def _walk_message_bodies(message: Message) -> list[str]:
    """Return decoded plain-text and HTML bodies from an email.Message."""
    texts: list[str] = []

    def _decode(payload: bytes | None, charset: str | None) -> str:
        if not payload:
            return ""
        return payload.decode(charset or "utf-8", errors="replace")

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            decoded = _decode(payload, part.get_content_charset())
            if decoded:
                texts.append(decoded)
    else:
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            decoded = _decode(payload, message.get_content_charset())
            if decoded:
                texts.append(decoded)
    return texts


def _try_logout(mail: Any) -> None:
    try:
        mail.logout()
    except (OSError, imaplib.IMAP4.error):
        # Best-effort logout; the connection is being discarded anyway.
        return


def poll_imap_for_verification(
    config: IMAPConfig,
    from_email: str | None = None,
    max_messages: int = 5,
) -> dict[str, Any]:
    """Poll an IMAP mailbox for a verification link/code (synchronous).

    Args:
        config: Mailbox configuration.
        from_email: Only search messages from this sender address (the
            address the signup was registered with).
        max_messages: How many recent messages to scan.

    Returns:
        ``{"success": bool, "link": str|None, "code": str|None, "error": str|None}``
    """
    try:
        mail = imaplib.IMAP4_SSL(config.host, config.port)
    except (OSError, imaplib.IMAP4.error) as exc:
        return {
            "success": False,
            "error": f"imap connect failed: {exc}",
            "link": None,
            "code": None,
        }

    try:
        mail.login(config.user, config.password)
        mail.select(config.mailbox)
        if from_email:
            status, data = mail.search(None, "FROM", f'"{from_email}"')
        else:
            status, data = mail.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return {"success": True, "link": None, "code": None}

        ids = data[0].split()
        for num in ids[-max_messages:]:
            fetch_status, msg_data = mail.fetch(num, "(RFC822)")
            if fetch_status != "OK" or not msg_data:
                continue
            bodies: list[str] = []
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2:
                    message = BytesParser().parsebytes(part[1])
                    bodies.extend(_walk_message_bodies(message))
            body_text = "\n".join(bodies)
            link, code = extract_verification_link(body_text)
            if link or code:
                return {"success": True, "link": link, "code": code}
        return {"success": True, "link": None, "code": None}
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"success": False, "error": f"imap error: {exc}", "link": None, "code": None}
    finally:
        _try_logout(mail)


# ---------------------------------------------------------------------------
# Temp-mail (mail.tm) fallback
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public orchestration
# ---------------------------------------------------------------------------


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
