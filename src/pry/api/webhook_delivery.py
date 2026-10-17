"""Pry — Webhook Delivery Service.
Reliable webhook delivery with retries, signing (HMAC), and dead letter queue."""

# Licensed under MIT. See LICENSE.
import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.api.webhook_support import (
    WebhookSecretNotConfigured,
    _is_production,
    _redact,
    _validate_url,
    resolve_secret,
    retry_dead_letter,
    retry_dead_letter_async,
)
from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

WEBHOOK_DIR = PRY_DATA_DIR / "webhooks"

_ATTEMPT_TIMEOUT = 10.0
_RETRY_DELAY = 5.0


class WebhookDelivery:
    """Deliver webhooks reliably with retries and HMAC signing."""

    def __init__(self, signing_secret: str = ""):
        WEBHOOK_DIR.mkdir(parents=True, exist_ok=True)
        # Secret resolution order: explicit arg → PRY_WEBHOOK_SECRET env →
        # settings.webhook_secret (which reads PRY_WEBHOOK_SECRET /
        # pry/webhook_secret in gopass — see settings.py).
        self.signing_secret, self._key_origin = resolve_secret(signing_secret)
        # settings._ensure_webhook_secret() GENERATES an ephemeral secret at
        # boot when none is configured. Signing with it silently breaks every
        # receiver after a restart, so treat a settings-sourced value as
        # ephemeral: persist a warning, and refuse to sign in production.
        self._ephemeral_secret = self._key_origin == "settings"
        self._refuse_signing = not self.signing_secret or (
            self._ephemeral_secret
            and _is_production()
            and os.getenv("PRY_ALLOW_EPHEMERAL_WEBHOOK_SECRET") != "1"
        )
        if self._ephemeral_secret or not self.signing_secret:
            self._persist_secret_warning()
        self.delivery_log = WEBHOOK_DIR / "deliveries.jsonl"
        self.dead_letter = WEBHOOK_DIR / "dead_letter.jsonl"
        self.log: list[dict] = []  # lazy-loaded by _load_log() on demand

    def _persist_secret_warning(self) -> None:
        """Persist (not just log) that the signing secret is not durable."""
        msg = (
            "webhook signing secret is EPHEMERAL (missing or generated at boot); "
            "signatures will not survive a restart. Set PRY_WEBHOOK_SECRET; "
            "signing is refused when PRY_ENV=production."
        )
        logger.warning("webhook_secret_ephemeral", extra={"source": self._key_origin})
        try:
            with open(WEBHOOK_DIR / "secret_warning.log", "a") as f:
                f.write(f"{datetime.now(UTC).isoformat()} {msg}\n")
        except OSError as e:
            logger.warning("webhook_secret_warning_write_failed", extra={"error": str(e)})

    @property
    def secret_configured(self) -> bool:
        return bool(self.signing_secret)

    def _load_log(self) -> None:
        self.log: list[dict] = []
        if self.delivery_log.exists():
            try:
                for line in self.delivery_log.read_text().splitlines():
                    if line.strip():
                        self.log.append(json.loads(line))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("webhook_log_load_failed", extra={"error": str(e)[:160]})

    def sign_payload(self, payload: dict, timestamp: str = "", event_type: str = "") -> str:
        if not self.signing_secret:
            raise WebhookSecretNotConfigured(
                "webhook signing secret is not configured — refusing to produce "
                "a forgeable signature. Set PRY_WEBHOOK_SECRET."
            )
        if self._refuse_signing:
            raise WebhookSecretNotConfigured(
                "webhook signing secret is ephemeral (generated at boot) and "
                "PRY_ENV=production — refusing to sign. Set PRY_WEBHOOK_SECRET."
            )
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signed = f"{timestamp}.{event_type}.{body}"
        return hmac.new(self.signing_secret.encode(), signed.encode(), hashlib.sha256).hexdigest()

    def _headers(self, payload: dict, event_type: str) -> dict[str, str]:
        ts = str(int(time.time()))
        sig = self.sign_payload(payload, timestamp=ts, event_type=event_type)
        return {
            "Content-Type": "application/json",
            "X-Pry-Event": event_type,
            "X-Pry-Signature": f"sha256={sig}",
            "X-Pry-Timestamp": ts,
        }

    async def _attempt(
        self, client: Any, ctx: dict[str, Any], attempt: int
    ) -> dict[str, Any] | None:
        url = ctx["url"]
        try:
            resp = await client.post(
                ctx["pinned_url"],
                json=ctx["payload"],
                headers=ctx["headers"],
                timeout=_ATTEMPT_TIMEOUT,
                follow_redirects=False,
                extensions={"sni_hostname": urllib.parse.urlparse(url).hostname or ""},
            )
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("webhook_delivery_exception_handler", exc_info=True)
            self._log(
                {
                    "url": url,
                    "attempt": attempt,
                    "error": str(e)[:200],
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            return None
        self._log(
            {
                "url": url,
                "event": ctx["event_type"],
                "attempt": attempt,
                "status": resp.status_code,
                "success": resp.is_success,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if resp.is_success:
            return {"success": True, "status": resp.status_code, "attempts": attempt}
        if resp.status_code < 500:
            if ctx["record_dead_letter"]:
                self._dead_letter(
                    ctx["payload"], url, f"HTTP {resp.status_code}", ctx["event_type"]
                )
            return {"success": False, "status": resp.status_code, "error": "Client error"}
        return None

    async def deliver(
        self,
        url: str,
        payload: dict,
        event_type: str = "monitor.change",
        max_retries: int = 3,
        record_dead_letter: bool = True,
    ) -> dict[str, Any]:
        """Deliver a webhook with retries; fail-closed when unsigned."""
        from pry.api.client import get_client

        pinned_url, rejection = _validate_url(url)
        if rejection:
            logger.warning("webhook_url_rejected", extra={"url": url, "reason": rejection})
            return {"success": False, "error": f"URL rejected: {rejection}"}
        try:
            headers = self._headers(payload, event_type)
        except WebhookSecretNotConfigured as e:
            logger.error(
                "webhook_delivery_refused_unsigned", extra={"url": url, "event": event_type}
            )
            return {"success": False, "error": str(e), "refused": True}
        ctx = {
            "pinned_url": pinned_url,
            "url": url,
            "payload": payload,
            "headers": headers,
            "event_type": event_type,
            "record_dead_letter": record_dead_letter,
        }
        sleep_budget = sum(_RETRY_DELAY * (2 ** (i - 1)) for i in range(1, max_retries))
        outer_budget = max_retries * _ATTEMPT_TIMEOUT + sleep_budget + 5.0
        client = await get_client()
        try:
            async with asyncio.timeout(outer_budget):
                for attempt in range(1, max_retries + 1):
                    done = await self._attempt(client, ctx, attempt)
                    if done is not None:
                        return done
                    if attempt < max_retries:
                        await asyncio.sleep(_RETRY_DELAY * (2 ** (attempt - 1)))
        except TimeoutError:
            logger.warning("webhook_delivery_exception_handler", exc_info=True)
            if record_dead_letter:
                self._dead_letter(
                    payload, url, f"Delivery timeout ({outer_budget:.0f}s)", event_type
                )
            return {"success": False, "error": "delivery timeout", "url": url}
        if record_dead_letter:
            self._dead_letter(payload, url, "Max retries exceeded", event_type)
        return {"success": False, "error": "Max retries exceeded", "delivered": False}

    def _log(self, record: dict) -> None:
        try:
            with open(self.delivery_log, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning("webhook_log_write_failed", extra={"error": str(e)})
        self.log.append(record)

    def _dead_letter(
        self, payload: dict, url: str, reason: str, event_type: str = "monitor.change"
    ) -> None:
        try:
            with open(self.dead_letter, "a") as f:
                record = {
                    "payload": _redact(payload),
                    "url": url,
                    "event": event_type,
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning("dead_letter_write_failed", extra={"error": str(e)})

    def get_dead_letter(self) -> list[dict]:
        items = []
        if self.dead_letter.exists():
            try:
                for line in self.dead_letter.read_text().splitlines():
                    if line.strip():
                        items.append(json.loads(line))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("webhook_log_load_failed", extra={"error": str(e)[:160]})
        return items

    def _write_dead_letter(self, items: list[dict]) -> None:
        tmp = self.dead_letter.with_suffix(".jsonl.tmp")
        try:
            with open(tmp, "w") as f:
                for item in items:
                    f.write(json.dumps(item) + "\n")
            os.replace(tmp, self.dead_letter)
        except OSError as e:
            logger.warning("dead_letter_write_failed", extra={"error": str(e)})

    async def _retry_dead_letter_async(self, limit: int) -> dict[str, Any]:
        return await retry_dead_letter_async(self, limit)

    def retry_dead_letter(self, limit: int = 20) -> dict[str, Any]:
        """Re-attempt dead-lettered webhooks via the normal signed path."""
        return retry_dead_letter(self, limit)
