"""Pry — Reverse ETL to CRM.
Sync scraped data to Salesforce, HubSpot, Pipedrive, and Close.com."""

# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def sync_to_salesforce(
    objects: list[dict[str, Any]],
    object_type: str = "Lead",
    instance_url: str = "",
    access_token: str = "",
) -> dict[str, Any]:
    """Sync scraped data to Salesforce objects.

    Args:
        objects: List of records to create/update
        object_type: Salesforce object type (Lead, Contact, Account, Opportunity)
        instance_url: Salesforce instance URL (e.g., https://yourInstance.salesforce.com)
        access_token: Salesforce OAuth2 access token
    """
    from pry.api.client import get_client

    client = await get_client()
    api_url = instance_url.rstrip("/")

    results = []
    for obj in objects:
        sf_obj = _map_to_salesforce(obj, object_type)
        try:
            resp = await client.post(
                f"{api_url}/services/data/v58.0/sobjects/{object_type}",
                json=sf_obj,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if resp.is_success:
                data = resp.json()
                results.append(
                    {
                        "success": True,
                        "salesforce_id": data.get("id"),
                        "name": obj.get("name") or obj.get("title", "Unknown"),
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": obj.get("name", "Unknown"),
                        "error": f"Salesforce error {resp.status_code}: {resp.text[:200]}",
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
        "platform": "salesforce",
        "object_type": object_type,
        "total": len(objects),
        "synced": success_count,
        "failed": len(objects) - success_count,
        "results": results,
    }


def _map_to_salesforce(data: dict[str, Any], object_type: str) -> dict[str, Any]:
    """Map common field names to Salesforce standard field names."""
    mapping = {
        "name": "LastName" if object_type == "Lead" else "Name",
        "first_name": "FirstName",
        "last_name": "LastName",
        "email": "Email",
        "phone": "Phone",
        "company": "Company",
        "title": "Title",
        "description": "Description",
        "website": "Website",
        "industry": "Industry",
        "address": "Street",
        "city": "City",
        "state": "State",
        "zip": "PostalCode",
        "country": "Country",
        "revenue": "AnnualRevenue",
        "employees": "NumberOfEmployees",
        "source_url": "LeadSource",
    }

    result = {}
    for src_key, sf_key in mapping.items():
        if data.get(src_key):
            result[sf_key] = data[src_key]

    for key, value in data.items():
        if key not in mapping and key not in ("_source", "_raw"):
            result[key[:120]] = (
                value if isinstance(value, (str, int, float, bool)) else str(value)[:255]
            )

    return result


async def sync_to_hubspot(
    objects: list[dict[str, Any]],
    object_type: str = "contacts",
    api_key: str = "",
) -> dict[str, Any]:
    """Sync scraped data to HubSpot CRM.

    Args:
        objects: List of contact/company/deal records
        object_type: contacts, companies, deals
        api_key: HubSpot Private App API key
    """
    from pry.api.client import get_client

    client = await get_client()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    results = []

    api_paths = {
        "contacts": "/crm/v3/objects/contacts",
        "companies": "/crm/v3/objects/companies",
        "deals": "/crm/v3/objects/deals",
    }
    api_path = api_paths.get(object_type, f"/crm/v3/objects/{object_type}")

    for obj in objects:
        properties = _map_to_hubspot(obj, object_type)
        payload = {"properties": properties}
        try:
            resp = await client.post(
                f"https://api.hubapi.com{api_path}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            if resp.is_success:
                data = resp.json()
                results.append(
                    {
                        "success": True,
                        "hubspot_id": data.get("id"),
                        "name": obj.get("name") or obj.get("email", "Unknown"),
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": obj.get("name", "Unknown"),
                        "error": f"HubSpot error {resp.status_code}: {resp.text[:200]}",
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
        "platform": "hubspot",
        "object_type": object_type,
        "total": len(objects),
        "synced": success_count,
        "failed": len(objects) - success_count,
        "results": results,
    }


def _map_to_hubspot(data: dict[str, Any], object_type: str) -> dict[str, str]:
    """Map common fields to HubSpot property names."""
    mapping: dict[str, str] = {
        "name": "firstname" if object_type == "contacts" else "name",
        "first_name": "firstname",
        "last_name": "lastname",
        "email": "email",
        "phone": "phone",
        "company": "company",
        "title": "jobtitle",
        "website": "website",
        "description": "description",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip": "zip",
        "country": "country",
        "industry": "industry",
    }
    properties = {}
    for src_key, hs_key in mapping.items():
        if data.get(src_key):
            properties[hs_key] = str(data[src_key])[:500]
    return properties


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
