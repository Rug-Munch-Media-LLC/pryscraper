# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Microsoft Graph / Outlook integration — list and parse messages."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from pry.engine.email_scraper.extractor import extract_email_data
from pry.engine.email_scraper.tokens import require_token


async def fetch_outlook_emails(
    access_token: str,
    max_results: int = 20,
    query: str = "",
    since_days: int = 7,
) -> dict[str, Any]:
    """Fetch emails from Outlook/Office 365 via Microsoft Graph API."""
    missing = require_token(access_token, "outlook")
    if missing is not None:
        return missing

    from pry.api.client import get_client

    client = await get_client()
    headers = {"Authorization": f"Bearer {access_token}"}

    since_date = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()

    try:
        params: dict[str, Any] = {
            "$top": min(max_results, 50),
            "$orderby": "receivedDateTime DESC",
            "$filter": f"receivedDateTime ge {since_date}",
        }
        if query:
            params["$search"] = f'"{query}"'

        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            params=params,
            headers=headers,
            timeout=15,
        )
        if not resp.is_success:
            return {"success": False, "error": f"Outlook API error {resp.status_code}"}

        data = resp.json()
        messages = data.get("value", [])
        emails = [_parse_outlook_message(msg) for msg in messages[:max_results]]

        return {"success": True, "total": len(emails), "emails": emails}

    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"success": False, "error": str(e)[:300]}


def _parse_outlook_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Parse a single Graph message into a structured email object."""
    subject = msg.get("subject", "")
    sender = msg.get("from", {}).get("emailAddress", {}).get("address", "")
    body_content = msg.get("body", {}).get("content", "")
    # Strip HTML
    body_text = re.sub(r"<[^>]+>", " ", body_content)

    extracted = extract_email_data(subject, body_text[:5000], sender)
    return {
        "id": msg.get("id"),
        "subject": subject[:200],
        "from": sender[:200],
        "date": msg.get("receivedDateTime", "")[:25],
        "email_type": extracted["email_type"],
        "extracted_data": extracted["extracted_data"],
    }
