"""Pry — Integrations router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pry.core.deps import scraper
from pry.core.errors import InvalidRequestError, ScrapeError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Integrations"])


@router.get(
    "/v1/destinations",
    tags=["Integrations"],
    summary="List supported data destinations",
)
async def list_destinations() -> dict[str, Any]:
    """List all supported data destinations and their config requirements."""
    return {
        "success": True,
        "data": {
            "destinations": [
                {
                    "id": "slack",
                    "name": "Slack",
                    "description": "Send data to a Slack channel via webhook",
                    "config_fields": ["webhook_url", "title"],
                },
                {
                    "id": "googlesheets",
                    "name": "Google Sheets",
                    "description": "Write data to a Google Spreadsheet",
                    "config_fields": ["spreadsheet_id", "range", "credentials_json"],
                },
                {
                    "id": "airtable",
                    "name": "Airtable",
                    "description": "Write records to an Airtable base",
                    "config_fields": ["base_id", "table_name", "api_key"],
                },
                {
                    "id": "email",
                    "name": "Email",
                    "description": "Send data via email (SMTP or mailto link)",
                    "config_fields": ["recipient", "subject", "smtp_host", "smtp_user"],
                },
            ]
        },
    }


@router.post(
    "/v1/destination/send",
    tags=["Integrations"],
    summary="Send scraped data to a business destination",
)
async def send_to_destination(
    destination: str = Body(...),
    data: dict[str, Any] = Body(...),
    config: dict[str, Any] = Body(...),
    url: str | None = Body(None),
) -> dict[str, Any]:
    """Send extracted data to a business destination in one click.

    Destinations:
    - slack: Send to Slack channel via webhook
    - googlesheets: Write to Google Sheets (requires credentials)
    - airtable: Write to Airtable base (requires API key)
    - email: Send via email (requires SMTP config)

    Config varies by destination:
    - slack: {"webhook_url": "https://hooks.slack.com/..."}
    - googlesheets: {"spreadsheet_id": "...", "credentials_json": "..."}
    - airtable: {"base_id": "...", "table_name": "Table 1", "api_key": "..."}
    - email: {"recipient": "user@example.com", "subject": "Data Export"}
    """
    from pry.commerce.destinations import SUPPORTED_DESTINATIONS, dispatch

    if destination not in SUPPORTED_DESTINATIONS:
        raise InvalidRequestError(
            f"Unsupported destination: {destination}. Supported: {SUPPORTED_DESTINATIONS}"
        )

    result = await dispatch(destination, data, config)
    return {"success": result["success"], "data": result}


@router.post(
    "/v1/scrape-and-send",
    tags=["Integrations"],
    summary="Scrape a URL and send to a destination",
)
async def scrape_and_send(
    url: str = Body(...),
    destination: str = Body(...),
    destination_config: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Scrape a URL and send the results to a business destination in one step.

    Combines /v1/scrape + /v1/destination/send into a single call.
    Perfect for non-technical users who just want data in their tools.
    """
    from pry.commerce.destinations import SUPPORTED_DESTINATIONS, dispatch

    if destination not in SUPPORTED_DESTINATIONS:
        raise InvalidRequestError(
            f"Unsupported destination: {destination}. Supported: {SUPPORTED_DESTINATIONS}"
        )

    # Scrape
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    # Send to destination
    send_result = await dispatch(destination, result.get("data", result), destination_config)

    return {
        "success": send_result["success"],
        "data": {
            "url": url,
            "destination": destination,
            "scrape_status": result.get("status"),
            "delivery": send_result,
        },
    }
