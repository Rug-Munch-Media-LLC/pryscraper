# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Account pool management, session persistence, proxy scoring."""

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

ACCOUNTS_DIR = PRY_DATA_DIR / "accounts"
ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)


class AccountPool:
    """Manage pool of registered accounts with session persistence."""

    def store(
        self,
        site: str,
        credentials: dict[str, Any],
        profile_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        import uuid

        account_id = uuid.uuid4().hex[:12]
        account: dict[str, Any] = {
            "id": account_id,
            "site": site,
            "credentials": credentials,
            "profile_id": profile_id,
            "metadata": metadata or {},
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
            "last_used": None,
            "use_count": 0,
            "errors": [],
        }
        path = ACCOUNTS_DIR / f"{site}_{account_id}.json"
        path.write_text(json.dumps(account, indent=2))
        logger.info("account_stored", extra={"site": site, "account_id": account_id})
        return account_id

    def get_active(self, site: str) -> dict[str, Any] | None:
        """Get a random active account for a site."""
        accounts = []
        for path in ACCOUNTS_DIR.glob(f"{site}_*.json"):
            try:
                acct = json.loads(path.read_text())
                if acct.get("status") == "active":
                    accounts.append(acct)
            except (json.JSONDecodeError, OSError):
                continue
        if not accounts:
            return None
        import random

        return random.choice(accounts)

    def mark_error(self, account_id: str, error: str) -> None:
        for path in ACCOUNTS_DIR.glob(f"*_{account_id}.json"):
            try:
                acct = json.loads(path.read_text())
                acct["errors"].append({"time": datetime.now(UTC).isoformat(), "error": error[:200]})
                if len(acct["errors"]) > 5:
                    acct["status"] = "suspended"
                path.write_text(json.dumps(acct, indent=2))
            except (json.JSONDecodeError, ValueError):
                pass

    def record_use(self, account_id: str) -> None:
        for path in ACCOUNTS_DIR.glob(f"*_{account_id}.json"):
            try:
                acct = json.loads(path.read_text())
                acct["last_used"] = datetime.now(UTC).isoformat()
                acct["use_count"] = acct.get("use_count", 0) + 1
                path.write_text(json.dumps(acct, indent=2))
            except (json.JSONDecodeError, ValueError):
                pass

    def list_accounts(self, site: str = "") -> list[dict[str, Any]]:
        accounts = []
        pattern = f"{site}_*.json" if site else "*_*.json"
        for path in sorted(ACCOUNTS_DIR.glob(pattern), key=os.path.getmtime, reverse=True)[:50]:
            try:
                data = json.loads(path.read_text())
                data.pop("credentials", None)  # Don't expose passwords
                accounts.append(data)
            except (json.JSONDecodeError, ValueError):
                continue
        return accounts


class ProxyScorer:
    """Score and rank proxies for reliability."""

    async def test_proxy(
        self, proxy_url: str, test_url: str = "https://httpbin.org/ip", timeout: int = 10
    ) -> dict[str, Any]:
        from client import get_client

        client = await get_client()
        start = time.time()
        try:
            resp = await client.get(test_url, timeout=timeout)
            elapsed = time.time() - start
            return {
                "proxy": proxy_url,
                "working": resp.is_success,
                "latency": round(elapsed, 2),
                "status": resp.status_code,
                "ip": resp.text[:50] if resp.is_success else "",
            }
        except (httpx.HTTPError, httpx.RequestError) as e:
            return {"proxy": proxy_url, "working": False, "error": str(e)[:80]}

    def score(self, test_result: dict[str, Any]) -> int:
        """Score proxy 0-100."""
        if not test_result.get("working"):
            return 0
        latency = test_result.get("latency", 99)
        if latency < 1:
            return 100
        if latency < 2:
            return 90
        if latency < 5:
            return 75
        if latency < 10:
            return 50
        return 25
