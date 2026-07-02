import httpx
"""Pry — Email Inbox Scraping.
Connect Gmail/Outlook, extract structured data from emails."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import base64
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ── Email Data Extraction Patterns ──

ORDER_PATTERNS = {
    "order_number": [
        r"order\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,20})",
        r"(?:order|ord)\s*[#:]?\s*([A-Z0-9]{5,20})",
        r"confirmation\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,20})",
    ],
    "total_amount": [
        r"total[:\s]*\$?([0-9,.]+)",
        r"amount[:\s]*\$?([0-9,.]+)",
        r"charged[:\s]*\$?([0-9,.]+)",
    ],
    "tracking_number": [
        r"tracking\s*(?:#|number|id|no)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"track\s*(?:#|number)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"shipment\s*(?:#|number|id)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
    ],
    "product_name": [
        r"(?:product|item|goods)[:\s]*(.+?)(?:\n|$)",
        r"purchased[:\s]*(.+?)(?:\n|$)",
        r"ordered[:\s]*(.+?)(?:\n|$)",
    ],
    "shipping_address": [
        r"shipping\s*(?:to|address)[:\s]*([A-Za-z0-9\s,\-]{10,100})",
        r"deliver\s*(?:to|address)[:\s]*([A-Za-z0-9\s,\-]{10,100})",
    ],
}

INVOICE_PATTERNS = {
    "invoice_number": [
        r"invoice\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,25})",
        r"inv\s*(?:#|no)[:\s]*([A-Z0-9\-]{5,25})",
    ],
    "due_date": [
        r"due\s*(?:date|by)[:\s]*([A-Za-z0-9\s,]+)",
        r"payment\s*(?:due|by)[:\s]*([A-Za-z0-9\s,]+)",
    ],
    "vendor": [
        r"(?:from|vendor|supplier)[:\s]*(.+?)(?:\n|$)",
        r"billed\s*(?:from|by)[:\s]*(.+?)(?:\n|$)",
    ],
}

SHIPPING_PATTERNS = {
    "tracking_number": [
        r"tracking\s*(?:#|number|id|no)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"track\s*(?:#|number)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"shipment\s*(?:#|number|id)[:\s]*(?:is\s+)?([A-Z0-9\-]{8,30})",
    ],
    "carrier": [
        r"(?:carrier|shipped\s*via|courier)[:\s]*(.+?)(?:\n|$)",
        r"(?:USPS|UPS|FedEx|DHL|Canada\s*Post|Royal\s*Mail)",
    ],
    "estimated_delivery": [
        r"estimated\s*(?:delivery|arrival)[:\s]*(.+?)(?:\n|$)",
        r"delivery\s*(?:date|by|on)[:\s]*([A-Za-z0-9\s,]+)",
        r"arriving\s*(?:on|by)[:\s]*([A-Za-z0-9\s,]+)",
    ],
}

RECEIPT_PATTERNS = {
    "receipt_number": [
        r"receipt\s*(?:#|number)[:\s]*([A-Z0-9\-]{5,25})",
        r"transaction\s*(?:#|id)[:\s]*([A-Z0-9\-]{5,30})",
    ],
    "payment_method": [
        r"payment\s*method[:\s]*(.+?)(?:\n|$)",
        r"paid\s*via[:\s]*(.+?)(?:\n|$)",
        r"card[:\s]*([A-Za-z0-9\s]{4,30})",
    ],
    "store_name": [
        r"(?:store|merchant|seller|retailer)[:\s]*(.+?)(?:\n|$)",
        r"purchased\s*(?:from|at)[:\s]*(.+?)(?:\n|$)",
        r"thank\s*you\s*for\s*(?:your\s*)?purchase\s*(?:from|at)?[:\s]*(.+?)(?:\n|$)",
    ],
}


def extract_email_data(subject: str, body: str, sender: str) -> dict[str, Any]:
    """Extract structured data from an email body.

    Returns extracted order/invoice/receipt information with confidence scores.
    """
    result: dict[str, Any] = {
        "sender": sender,
        "subject": subject,
        "email_type": _classify_email(subject, body),
        "extracted_data": {},
    }

    email_type = result["email_type"]
    patterns = _get_patterns_for_type(email_type)

    for field, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                result["extracted_data"][field] = match.group(1).strip()
                break

    # Extract monetary amounts
    amounts = re.findall(r"\$?([0-9]+(?:\.[0-9]{2})?)", body)
    if amounts and "total_amount" not in result["extracted_data"]:
        # Take the largest amount as most significant
        numeric = [float(a) for a in amounts if re.match(r"^\d+\.?\d*$", a)]
        if numeric:
            result["extracted_data"]["potential_amount"] = max(numeric)

    # Extract dates
    dates = re.findall(r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", body)
    if dates:
        result["extracted_data"]["dates_found"] = dates[:3]

    # Extract URLs
    urls = re.findall(r'https?://(?:www\.)?[^\s<>"]+', body)
    if urls:
        result["extracted_data"]["urls_found"] = urls[:5]

    return result


def _classify_email(subject: str, body: str) -> str:
    """Classify an email as order_confirmation, invoice, receipt, or other."""
    combined = (subject + " " + body[:500]).lower()
    if any(
        w in combined for w in ["order confirmation", "your order", "order received", "order #"]
    ):
        return "order_confirmation"
    if any(w in combined for w in ["invoice", "payment due", "billing statement", "invoice #"]):
        return "invoice"
    if any(
        w in combined for w in ["receipt", "your receipt", "payment receipt", "transaction receipt"]
    ):
        return "receipt"
    if any(w in combined for w in ["shipping", "shipment", "tracking", "on its way", "dispatched"]):
        return "shipping_notification"
    if any(w in combined for w in ["subscription", "renewal", "billed"]):
        return "subscription"
    return "other"


def _get_patterns_for_type(email_type: str) -> dict[str, list[str]]:
    """Get extraction patterns for the classified email type."""
    if email_type == "order_confirmation":
        return ORDER_PATTERNS
    if email_type == "invoice":
        return INVOICE_PATTERNS
    if email_type == "receipt":
        return RECEIPT_PATTERNS
    if email_type == "shipping_notification":
        return SHIPPING_PATTERNS
    return {}


# ── Gmail Integration ──


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
    from client import get_client

    client = await get_client()
    headers = {"Authorization": f"Bearer {access_token}"}

    # Build query
    since_date = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y/%m/%d")
    full_query = f"after:{since_date} {query}".strip()

    try:
        # List messages
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

        data = resp.json()
        messages = data.get("messages", [])

        if not messages:
            return {
                "success": True,
                "total": 0,
                "emails": [],
                "note": "No emails found matching query",
            }

        # Fetch each message
        emails = []
        for msg in messages[:max_results]:
            msg_id = msg["id"]
            try:
                msg_resp = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    headers=headers,
                    timeout=15,
                )
                if not msg_resp.is_success:
                    continue

                msg_data = msg_resp.json()
                email = _parse_gmail_message(msg_data)
                if email:
                    emails.append(email)
            except (httpx.HTTPError, httpx.RequestError) as e:
                logger.warning(
                    "gmail_fetch_failed", extra={"msg_id": msg_id, "error": str(e)[:100]}
                )
                continue

        return {"success": True, "total": len(emails), "emails": emails}

    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"success": False, "error": str(e)[:300]}


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
        except Exception:  # noqa: BLE001
            return ""

    # Check parts
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
        # Recursive check
        if part.get("parts"):
            result = _get_gmail_body(part)
            if result:
                return result

    return ""


# ── Microsoft Graph / Outlook Integration ──


async def fetch_outlook_emails(
    access_token: str,
    max_results: int = 20,
    query: str = "",
    since_days: int = 7,
) -> dict[str, Any]:
    """Fetch emails from Outlook/Office 365 via Microsoft Graph API."""
    from client import get_client

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
        emails = []

        for msg in messages[:max_results]:
            subject = msg.get("subject", "")
            sender = msg.get("from", {}).get("emailAddress", {}).get("address", "")
            body_content = msg.get("body", {}).get("content", "")
            # Strip HTML
            body_text = re.sub(r"<[^>]+>", " ", body_content)

            extracted = extract_email_data(subject, body_text[:5000], sender)
            emails.append(
                {
                    "id": msg.get("id"),
                    "subject": subject[:200],
                    "from": sender[:200],
                    "date": msg.get("receivedDateTime", "")[:25],
                    "email_type": extracted["email_type"],
                    "extracted_data": extracted["extracted_data"],
                }
            )

        return {"success": True, "total": len(emails), "emails": emails}

    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"success": False, "error": str(e)[:300]}
