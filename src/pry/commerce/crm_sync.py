"""Pry — Reverse ETL to CRM.
Sync scraped data to Salesforce, HubSpot, Pipedrive, and Close.com."""

# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from pry.commerce.crm_connectors import (  # noqa: F401 - re-exported API
    _map_to_hubspot,
    _map_to_salesforce,
    sync_to_hubspot,
    sync_to_salesforce,
)





async def sync_to_pipedrive(
    objects: list[dict[str, Any]],
    object_type: str = "person",
    api_token: str = "",
    domain: str = "",
) -> dict[str, Any]:
    """Sync scraped data to Pipedrive CRM."""
    from pry.api.client import get_client

    client = await get_client()
    domain = domain or "mycompany"
    results = []

    api_paths = {
        "person": "/v1/persons",
        "organization": "/v1/organizations",
        "deal": "/v1/deals",
        "lead": "/v1/leads",
    }
    path = api_paths.get(object_type, "/v1/persons")
    base = f"https://{domain}.pipedrive.com/api{path}"

    for obj in objects:
        fields = _map_to_pipedrive(obj, object_type)
        fields["api_token"] = api_token
        try:
            resp = await client.post(base, json=fields, timeout=30)
            if resp.is_success:
                data = resp.json()
                results.append(
                    {
                        "success": True,
                        "pipedrive_id": data.get("data", {}).get("id"),
                        "name": obj.get("name", "Unknown"),
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": obj.get("name", "Unknown"),
                        "error": f"Pipedrive error {resp.status_code}",
                    }
                )
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("crm_sync_suppressed", exc_info=True)
            results.append(
                {
                    "success": False,
                    "name": obj.get("name", "Unknown"),
                    "error": str(e)[:200],
                }
            )

    success_count = sum(1 for r in results if r["success"])
    return {
        "success": success_count > 0,
        "platform": "pipedrive",
        "total": len(objects),
        "synced": success_count,
        "failed": len(objects) - success_count,
        "results": results,
    }


def _map_to_pipedrive(data: dict[str, Any], object_type: str) -> dict[str, Any]:
    mapping = {
        "name": "name",
        "email": "email",
        "phone": "phone",
        "company": "org_name",
        "title": "title",
    }
    result: dict[str, Any] = {}
    for src_key, pd_key in mapping.items():
        if data.get(src_key):
            result[pd_key] = str(data[src_key])[:500]
    if object_type == "person" and "email" in result:
        result["email"] = [{"value": result["email"], "primary": True}]
    return result


async def sync_to_close(
    objects: list[dict[str, Any]],
    object_type: str = "lead",
    api_key: str = "",
) -> dict[str, Any]:
    """Sync scraped data to Close.com CRM."""
    import base64

    from pry.api.client import get_client

    client = await get_client()
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    results = []

    for obj in objects:
        close_obj = {
            "name": obj.get("name") or obj.get("title", "Unknown"),
            "description": (obj.get("description") or obj.get("content", ""))[:500],
            "url": obj.get("url", ""),
        }
        if obj.get("email"):
            close_obj["contacts"] = [{"emails": [{"email": obj["email"]}]}]
        try:
            resp = await client.post(
                "https://api.close.com/api/v1/lead/",
                json=close_obj,
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.is_success:
                data = resp.json()
                results.append(
                    {
                        "success": True,
                        "close_id": data.get("id"),
                        "name": obj.get("name", "Unknown"),
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": obj.get("name", "Unknown"),
                        "error": f"Close error {resp.status_code}: {resp.text[:200]}",
                    }
                )
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("crm_sync_suppressed", exc_info=True)
            results.append(
                {"success": False, "name": obj.get("name", "Unknown"), "error": str(e)[:200]}
            )

    success_count = sum(1 for r in results if r["success"])
    return {
        "success": success_count > 0,
        "platform": "close",
        "total": len(objects),
        "synced": success_count,
        "failed": len(objects) - success_count,
        "results": results,
    }
