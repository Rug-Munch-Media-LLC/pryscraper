"""Pry — Webhook Delivery Service.
Reliable webhook delivery with retries, signing (HMAC), and dead letter queue."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

WEBHOOK_DIR = PRY_DATA_DIR / "webhooks"
WEBHOOK_DIR.mkdir(parents=True, exist_ok=True)


class WebhookDelivery:
    """Deliver webhooks reliably with retries and HMAC signing."""

    DEFAULT_SIGNING_SECRET = "change-me-in-production"

    def __init__(self, signing_secret: str = ""):
        self.signing_secret = signing_secret or os.getenv(
            "PRY_WEBHOOK_SECRET", self.DEFAULT_SIGNING_SECRET
        )
        self.delivery_log = WEBHOOK_DIR / "deliveries.jsonl"
        self.dead_letter = WEBHOOK_DIR / "dead_letter.jsonl"
        self._load_log()

    def _load_log(self) -> None:
        self.log: list[dict] = []
        if self.delivery_log.exists():
            try:
                for line in self.delivery_log.read_text().splitlines():
                    if line.strip():
                        self.log.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                pass

    def sign_payload(self, payload: dict) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(self.signing_secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    async def deliver(
        self,
        url: str,
        payload: dict,
        event_type: str = "monitor.change",
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> dict[str, Any]:
        """Deliver a webhook with retries."""
        from client import get_client

        signature = self.sign_payload(payload)
        headers = {
            "Content-Type": "application/json",
            "X-Pry-Event": event_type,
            "X-Pry-Signature": f"sha256={signature}",
            "X-Pry-Timestamp": str(int(time.time())),
        }
        client = await get_client()
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers, timeout=10)
                record = {
                    "url": url,
                    "event": event_type,
                    "attempt": attempt,
                    "status": resp.status_code,
                    "success": resp.is_success,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                self._log(record)
                if resp.is_success:
                    return {"success": True, "status": resp.status_code, "attempts": attempt}
                if resp.status_code < 500:
                    self._dead_letter(payload, url, f"HTTP {resp.status_code}")
                    return {"success": False, "status": resp.status_code, "error": "Client error"}
            except (httpx.HTTPError, httpx.RequestError) as e:
                record = {
                    "url": url,
                    "attempt": attempt,
                    "error": str(e)[:200],
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                self._log(record)
            if attempt < max_retries:
                await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))
        self._dead_letter(payload, url, "Max retries exceeded")
        return {"success": False, "error": "Max retries exceeded", "delivered": False}

    def _log(self, record: dict) -> None:
        try:
            with open(self.delivery_log, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning("webhook_log_write_failed", extra={"error": str(e)})
        self.log.append(record)

    def _dead_letter(self, payload: dict, url: str, reason: str) -> None:
        try:
            with open(self.dead_letter, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "payload": payload,
                            "url": url,
                            "reason": reason,
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
                    + "\n"
                )
        except OSError as e:
            logger.warning("dead_letter_write_failed", extra={"error": str(e)})

    def get_dead_letter(self) -> list[dict]:
        items = []
        if self.dead_letter.exists():
            try:
                for line in self.dead_letter.read_text().splitlines():
                    if line.strip():
                        items.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                pass
        return items

    def retry_dead_letter(self) -> dict[str, Any]:
        items = self.get_dead_letter()
        return {"total": len(items), "items": items[:20]}
