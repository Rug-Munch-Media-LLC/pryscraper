"""Synchronous IMAP mailbox verification polling."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import imaplib
import logging
from email.parser import BytesParser
from typing import TYPE_CHECKING, Any

from pry.commerce.signup.email_verification.common import (
    IMAPConfig,
    extract_verification_link,
)

if TYPE_CHECKING:
    from email.message import Message

logger = logging.getLogger(__name__)


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
        logger.warning("imap_suppressed", exc_info=True)
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
        logger.warning("imap_suppressed", exc_info=True)
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
        logger.warning("imap_suppressed", exc_info=True)
        return {"success": False, "error": f"imap error: {exc}", "link": None, "code": None}
    finally:
        _try_logout(mail)
