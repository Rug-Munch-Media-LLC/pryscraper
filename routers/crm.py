"""Pry — CRM router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["CRM"])


@router.post("/v1/crm/sync", tags=["CRM"], summary="Sync scraped data to CRM")
async def sync_crm(
    platform: str = Body(...),
    object_type: str = Body("lead"),
    objects: list[dict[str, Any]] = Body(...),
    credentials: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Sync scraped data to your CRM.

    Platforms:
    - salesforce: credentials={"instance_url": "...", "access_token": "..."}
    - hubspot: credentials={"api_key": "..."}
    - pipedrive: credentials={"api_token": "...", "domain": "..."}
    - close: credentials={"api_key": "..."}

    Object types vary by platform:
    - Salesforce: Lead, Contact, Account, Opportunity
    - HubSpot: contacts, companies, deals
    - Pipedrive: person, organization, deal, lead
    - Close: lead, contact
    """
    from pry.commerce.crm_sync import (
        sync_to_close,
        sync_to_hubspot,
        sync_to_pipedrive,
        sync_to_salesforce,
    )

    platform_map: dict[str, tuple[Any, tuple[str, ...]]] = {
        "salesforce": (sync_to_salesforce, ("instance_url", "access_token")),
        "hubspot": (sync_to_hubspot, ("api_key",)),
        "pipedrive": (sync_to_pipedrive, ("api_token",)),
        "close": (sync_to_close, ("api_key",)),
    }

    if platform not in platform_map:
        raise InvalidRequestError(
            f"Unsupported platform: {platform}. Supported: {list(platform_map.keys())}"
        )

    handler: Any
    required_fields: tuple[str, ...]
    handler, required_fields = platform_map[platform]
    for field in required_fields:
        if not credentials.get(field):
            raise InvalidRequestError(f"Missing required credential: {field}")

    if platform == "salesforce":
        result = await handler(
            objects, object_type, credentials["instance_url"], credentials["access_token"]
        )
    elif platform == "hubspot":
        result = await handler(objects, object_type, credentials["api_key"])
    elif platform == "pipedrive":
        result = await handler(
            objects, object_type, credentials["api_token"], credentials.get("domain", "")
        )
    elif platform == "close":
        result = await handler(objects, object_type, credentials["api_key"])
    else:
        raise InvalidRequestError(f"Platform {platform} not handled")

    return {"success": result["success"], "data": result}


@router.get("/v1/crm/platforms", tags=["CRM"], summary="List supported CRM platforms")
async def list_crm_platforms() -> dict[str, Any]:
    """List supported CRM platforms and their credential requirements."""
    return {
        "success": True,
        "data": {
            "platforms": [
                {
                    "id": "salesforce",
                    "name": "Salesforce",
                    "objects": ["Lead", "Contact", "Account", "Opportunity"],
                    "credential_fields": ["instance_url", "access_token"],
                },
                {
                    "id": "hubspot",
                    "name": "HubSpot",
                    "objects": ["contacts", "companies", "deals"],
                    "credential_fields": ["api_key"],
                },
                {
                    "id": "pipedrive",
                    "name": "Pipedrive",
                    "objects": ["person", "organization", "deal", "lead"],
                    "credential_fields": ["api_token", "domain"],
                },
                {
                    "id": "close",
                    "name": "Close.com",
                    "objects": ["lead", "contact"],
                    "credential_fields": ["api_key"],
                },
            ]
        },
    }
