"""Pry — Email router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Email"])


@router.post(
    "/v1/email/scrape", tags=["Email"], summary="Extract data from an email (subject + body)"
)
async def scrape_email(
    subject: str = Body(""),
    body: str = Body(""),
    sender: str = Body(""),
) -> dict[str, Any]:
    """Extract structured data from an email subject and body.

    Auto-classifies as: order_confirmation, invoice, receipt,
    shipping_notification, subscription, or other.

    Extracts: order numbers, amounts, tracking numbers, dates, addresses.
    """
    from pry.engine.email_scraper import extract_email_data

    result = extract_email_data(subject, body, sender)
    return {"success": True, "data": result}


@router.post("/v1/email/gmail", tags=["Email"], summary="Fetch and extract data from Gmail inbox")
async def fetch_gmail(
    access_token: str = Body(...),
    max_results: int = Body(20),
    query: str = Body(""),
    since_days: int = Body(7),
) -> dict[str, Any]:
    """Connect to Gmail and extract structured data from emails.

    Requires a Gmail OAuth2 access token with scope:
    https://www.googleapis.com/auth/gmail.readonly

    Extracts order confirmations, invoices, receipts, shipping notifications.
    """
    from pry.engine.email_scraper import fetch_gmail_emails

    result = await fetch_gmail_emails(access_token, max_results, query, since_days)
    return {"success": result.get("success", False), "data": result}


@router.post(
    "/v1/email/outlook", tags=["Email"], summary="Fetch and extract data from Outlook inbox"
)
async def fetch_outlook(
    access_token: str = Body(...),
    max_results: int = Body(20),
    query: str = Body(""),
    since_days: int = Body(7),
) -> dict[str, Any]:
    """Connect to Outlook/Office 365 and extract structured data from emails.

    Requires a Microsoft Graph OAuth2 access token with scope:
    https://graph.microsoft.com/Mail.Read

    Extracts order confirmations, invoices, receipts, shipping notifications.
    """
    from pry.engine.email_scraper import fetch_outlook_emails

    result = await fetch_outlook_emails(access_token, max_results, query, since_days)
    return {"success": result.get("success", False), "data": result}
