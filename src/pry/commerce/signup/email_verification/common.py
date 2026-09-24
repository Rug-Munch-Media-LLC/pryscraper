"""Shared verification extraction and mailbox configuration."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import unquote

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


@dataclass
class IMAPConfig:
    """IMAP mailbox credentials for verification polling."""

    host: str
    user: str
    password: str
    port: int = 993
    mailbox: str = "INBOX"
