"""Pry — White-Label Agency Dashboard.
Multi-tenant reseller platform: custom branding, client management, sub-accounts."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)
AGENCY_DIR = PRY_DATA_DIR / "agency"
AGENCY_DIR.mkdir(parents=True, exist_ok=True)


# ── Agency Profile ──
def create_agency(
    name: str,
    owner_email: str,
    custom_domain: str = "",
    brand_color: str = "#f59e0b",
    logo_url: str = "",
) -> dict[str, Any]:
    """Create an agency profile with white-label settings."""
    agency_id = uuid.uuid4().hex[:12]
    agency = {
        "id": agency_id,
        "name": name,
        "owner_email": owner_email,
        "custom_domain": custom_domain,
        "brand_color": brand_color,
        "logo_url": logo_url,
        "created_at": datetime.now(UTC).isoformat(),
        "client_count": 0,
        "total_usage_requests": 0,
        "plan": "agency",
        "features": {
            "white_label": True,
            "custom_domain": bool(custom_domain),
            "client_portal": True,
            "usage_analytics": True,
            "api_access": True,
        },
    }
    path = AGENCY_DIR / f"agency_{agency_id}.json"
    try:
        path.write_text(json.dumps(agency, indent=2))
        logger.info("agency_created", extra={"agency_id": agency_id, "agency_name": name})
        return {"success": True, "agency": agency}
    except OSError as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


def get_agency(agency_id: str) -> dict[str, Any] | None:
    """Get agency profile."""
    path = AGENCY_DIR / f"agency_{agency_id}.json"
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        logger.warning("agency_suppressed", exc_info=True)
        return None


def update_agency_branding(
    agency_id: str,
    name: str | None = None,
    brand_color: str | None = None,
    logo_url: str | None = None,
    custom_domain: str | None = None,
) -> dict[str, Any]:
    """Update agency white-label branding."""
    agency = get_agency(agency_id)
    if not agency:
        return {"success": False, "error": "Agency not found"}
    if name:
        agency["name"] = name
    if brand_color:
        agency["brand_color"] = brand_color
    if logo_url:
        agency["logo_url"] = logo_url
    if custom_domain is not None:
        agency["custom_domain"] = custom_domain
        agency["features"]["custom_domain"] = bool(custom_domain)
    agency["updated_at"] = datetime.now(UTC).isoformat()
    path = AGENCY_DIR / f"agency_{agency_id}.json"
    try:
        path.write_text(json.dumps(agency, indent=2))
        return {"success": True, "agency": agency}
    except OSError as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


# ── Client Management ──


def create_client(
    agency_id: str,
    client_name: str,
    client_email: str,
    monthly_quota: int = 10000,
) -> dict[str, Any]:
    """Create a sub-account client under an agency."""
    client_id = uuid.uuid4().hex[:12]
    api_key = uuid.uuid4().hex[:24]
    client = {
        "id": client_id,
        "agency_id": agency_id,
        "name": client_name,
        "email": client_email,
        "api_key": api_key,
        "monthly_quota": monthly_quota,
        "usage_this_month": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "active",
        "settings": {
            "notify_on_usage": True,
            "usage_alert_threshold": 80,  # %
        },
    }
    path = AGENCY_DIR / f"client_{client_id}.json"
    try:
        path.write_text(json.dumps(client, indent=2))
        # Update agency client count
        agency = get_agency(agency_id)
        if agency:
            agency["client_count"] = agency.get("client_count", 0) + 1
            update_agency_branding(agency_id, name=agency["name"])
        logger.info("client_created", extra={"client_id": client_id, "agency_id": agency_id})
        return {"success": True, "client": {k: v for k, v in client.items() if k != "api_key"}}
    except OSError as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


def get_client(client_id: str) -> dict[str, Any] | None:
    """Get client details."""
    path = AGENCY_DIR / f"client_{client_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Strip API key from response
        return {k: v for k, v in data.items() if k != "api_key"}
    except (json.JSONDecodeError, OSError):
        logger.warning("agency_suppressed", exc_info=True)
        return None


def list_clients(agency_id: str) -> list[dict[str, Any]]:
    """List all clients for an agency."""
    clients = []
    for path in sorted(AGENCY_DIR.glob("client_*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            if data.get("agency_id") == agency_id:
                clients.append({k: v for k, v in data.items() if k != "api_key"})
        except (json.JSONDecodeError, OSError):
            logger.warning("agency_suppressed", exc_info=True)
            continue
    return clients


def update_client_quota(client_id: str, new_quota: int) -> dict[str, Any]:
    """Update a client's monthly usage quota."""
    path = AGENCY_DIR / f"client_{client_id}.json"
    if not path.exists():
        return {"success": False, "error": "Client not found"}
    try:
        client = json.loads(path.read_text())
        client["monthly_quota"] = new_quota
        path.write_text(json.dumps(client, indent=2))
        return {"success": True, "client_id": client_id, "monthly_quota": new_quota}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


def record_client_usage(client_id: str, requests: int = 1) -> dict[str, Any]:
    """Record API usage for a client."""
    path = AGENCY_DIR / f"client_{client_id}.json"
    if not path.exists():
        return {"success": False, "error": "Client not found"}
    try:
        client = json.loads(path.read_text())
        client["usage_this_month"] = client.get("usage_this_month", 0) + requests
        path.write_text(json.dumps(client, indent=2))
        return {"success": True, "usage": client["usage_this_month"]}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


def check_client_quota(client_id: str) -> dict[str, Any]:
    """Check if a client has exceeded their quota."""
    path = AGENCY_DIR / f"client_{client_id}.json"
    if not path.exists():
        return {"success": False, "error": "Client not found"}
    try:
        client = json.loads(path.read_text())
        usage = client.get("usage_this_month", 0)
        quota = client.get("monthly_quota", 0)
        percent = round(usage / quota * 100, 1) if quota > 0 else 0
        return {
            "success": True,
            "client_id": client_id,
            "usage": usage,
            "quota": quota,
            "percent_used": percent,
            "exceeded": usage >= quota,
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("agency_suppressed", exc_info=True)
        return {"success": False, "error": str(e)}


# ── Usage Analytics ──


def get_agency_analytics(agency_id: str) -> dict[str, Any]:
    """Get aggregate usage analytics for an agency."""
    clients = list_clients(agency_id)
    total_usage = 0
    total_quota = 0
    active_clients = 0
    exceeded_clients = 0

    for client in clients:
        usage = AGENCY_DIR / f"client_{client['id']}.json"
        if usage.exists():
            try:
                data = json.loads(usage.read_text())
                total_usage += data.get("usage_this_month", 0)
                total_quota += data.get("monthly_quota", 0)
                if data.get("status") == "active":
                    active_clients += 1
                if data.get("usage_this_month", 0) >= data.get("monthly_quota", 0):
                    exceeded_clients += 1
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("agency_client_usage_load_failed", extra={"error": str(e)[:160]})

    return {
        "agency_id": agency_id,
        "total_clients": len(clients),
        "active_clients": active_clients,
        "total_usage": total_usage,
        "total_quota": total_quota,
        "usage_percent": round(total_usage / total_quota * 100, 1) if total_quota > 0 else 0,
        "clients_exceeding_quota": exceeded_clients,
    }
