# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Gmail API integration — list, fetch, and parse messages."""

import base64
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from pry.engine.email_scraper.extractor import extract_email_data
from pry.engine.email_scraper.tokens import require_token

logger = logging.getLogger(__name__)


async def fetch_gmail_emails(
    access_token: str,
    max_results: int = 20,
    query: str = "",
    since_days: int = 7,
) -> dict[str, Any]:
    """Fetch emails from Gmail via the Gmail API.

    Args:
        access_token: Gmail OAuth2 access token
        max_results: Maximum number of emails to fetch
        query: Gmail search query (e.g., "from:amazon subject:order")
        since_days: Fetch emails from this many days ago

    Returns list of emails with extracted data.
    """
    missing = require_token(access_token, "gmail")
    if missing is not None:
        return missing

    from pry.api.client import get_client

    client = await get_client()
    headers = {"Authorization": f"Bearer {access_token}"}

    # Build query
    since_date = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y/%m/%d")
    full_query = f"after:{since_date} {query}".strip()

    try:
        resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"q": full_query, "maxResults": min(max_results, 50)},
            headers=headers,
            timeout=15,
        )
        if not resp.is_success:
            return {
                "success": False,
                "error": f"Gmail API error {resp.status_code}: {resp.text[:200]}",
            }

        messages = resp.json().get("messages", [])
        if not messages:
            return {
                "success": True,
                "total": 0,
                "emails": [],
                "note": "No emails found matching query",
            }

        emails, failed_ids = await _fetch_message_bodies(client, headers, messages[:max_results])
        return _build_result(emails, failed_ids)

    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("silent_exception_swallowed", exc_info=True)
        return {"success": False, "error": str(e)[:300]}


def _build_result(emails: list[dict[str, Any]], failed_ids: list[str]) -> dict[str, Any]:
    """Assemble the Gmail response, flagging partial content gaps."""
    result: dict[str, Any] = {"success": True, "total": len(emails), "emails": emails}
    if failed_ids:
        # The listing succeeded but the contents of these messages did
        # not: report the partial result as partial instead of a clean
        # success that silently drops the gaps.
        result["partial"] = True
        result["failed_count"] = len(failed_ids)
        result["note"] = f"{len(failed_ids)} message(s) failed to fetch"
    return result


async def _fetch_message_bodies(
    client: Any, headers: dict[str, str], msg_ids: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch and parse each message body.

    Returns ``(emails, failed_ids)`` rather than dropping failures: a message
    whose content cannot be fetched is a GAP, and a caller told
    ``{"success": True}`` with no gap count will treat the batch as complete.
    """
    emails: list[dict[str, Any]] = []
    failed_ids: list[str] = []
    for msg in msg_ids:
        msg_id = msg["id"]
        try:
            msg_resp = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                headers=headers,
                timeout=15,
            )
            if not msg_resp.is_success:
                failed_ids.append(msg_id)
                continue
            email = _parse_gmail_message(msg_resp.json())
            if email:
                emails.append(email)
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("gmail_fetch_failed", extra={"msg_id": msg_id, "error": str(e)[:100]})
            failed_ids.append(msg_id)
    return emails, failed_ids


def _parse_gmail_message(msg_data: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a single Gmail message into a structured email object."""
    payload = msg_data.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    date_str = headers.get("date", "")
    body = _get_gmail_body(payload)

    if not body:
        return None

    extracted = extract_email_data(subject, body[:5000], sender)

    return {
        "id": msg_data.get("id"),
        "thread_id": msg_data.get("threadId"),
        "subject": subject[:200],
        "from": sender[:200],
        "date": date_str[:50],
        "snippet": msg_data.get("snippet", "")[:200],
        "email_type": extracted["email_type"],
        "extracted_data": extracted["extracted_data"],
    }


def _get_gmail_body(payload: dict[str, Any]) -> str:
    """Extract body text from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return ""

    # Check parts
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                logger.warning("silent_exception_swallowed", exc_info=True)
                continue
        # Recursive check
        if part.get("parts"):
            result = _get_gmail_body(part)
            if result:
                return result

    return ""
