"""Pry — Webhook Delivery Service.
Reliable webhook delivery with retries, signing (HMAC), and dead letter queue."""

# Licensed under MIT. See LICENSE.
import asyncio
import concurrent.futures
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import time
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.core.paths import PRY_DATA_DIR
from pry.core.settings import settings

logger = logging.getLogger(__name__)

WEBHOOK_DIR = PRY_DATA_DIR / "webhooks"

_REDACT_KEYS = ("token", "secret", "password", "api_key", "authorization")
_PRODUCTION_ENVS = frozenset({"production", "prod"})
_ATTEMPT_TIMEOUT = 10.0


def _is_production() -> bool:
    env = (os.getenv("PRY_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in _PRODUCTION_ENVS


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys in nested objects and arrays."""
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if any(n in str(k).lower() for n in _REDACT_KEYS) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _validate_url(url: str) -> tuple[None, str] | tuple[str, None]:
    """Validate webhook URL to prevent SSRF.

    Returns ``(url, None)`` if safe — the returned URL has its hostname
    replaced by the PINNED validated IP, closing the DNS-rebinding TOCTOU
    window (validate-then-connect would otherwise re-resolve at connect
    time). Returns ``(None, reason)`` when rejected.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        logger.warning("webhook_delivery_exception_handler", exc_info=True)
        return None, "invalid URL"
    if not parsed.hostname:
        return None, "missing hostname"
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http"):
        return None, f"unsupported scheme: {scheme}"
    if scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return None, "http only allowed for localhost"
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        logger.warning("webhook_delivery_exception_handler", exc_info=True)
        return None, "hostname unresolvable"
    # Resolve once, validate every address, and pin the FIRST address.
    # httpx connects to the pinned IP; the original hostname is preserved
    # for TLS SNI + the Host header via extensions below.
    validated_ip: str | None = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None, f"host resolves to private/loopback IP: {ip}"
        if validated_ip is None:
            validated_ip = str(ip)
    if validated_ip is None:
        return None, "hostname unresolvable"
    # Rebuild the URL against the pinned IP. IPv6 literals need brackets.
    host_literal = f"[{validated_ip}]" if ":" in validated_ip else validated_ip
    netloc = host_literal
    if parsed.port:
        netloc = f"{host_literal}:{parsed.port}"
    pinned = parsed._replace(netloc=netloc).geturl()
    return pinned, None


class WebhookSecretNotConfigured(RuntimeError):
    """Raised when signing is attempted without a configured secret.

    An HMAC computed with an empty key is forgeable by anyone, so delivering
    a 'signed' webhook with no secret would give receivers false integrity
    guarantees. Delivery is refused instead (fail-closed).
    """


class WebhookDelivery:
    """Deliver webhooks reliably with retries and HMAC signing."""

    def __init__(self, signing_secret: str = ""):
        WEBHOOK_DIR.mkdir(parents=True, exist_ok=True)
        # Secret resolution order: explicit arg → PRY_WEBHOOK_SECRET env →
        # settings.webhook_secret (which reads PRY_WEBHOOK_SECRET /
        # pry/webhook_secret in gopass — see settings.py).
        self.signing_secret = (
            signing_secret or os.getenv("PRY_WEBHOOK_SECRET") or settings.webhook_secret
        )
        # settings._ensure_webhook_secret() GENERATES an ephemeral secret at
        # boot when none is configured. Signing with it silently breaks every
        # receiver after a restart, so treat a settings-sourced value as
        # ephemeral: persist a warning, and refuse to sign in production.
        if signing_secret:
            self._key_origin = "explicit"
        elif os.getenv("PRY_WEBHOOK_SECRET"):
            self._key_origin = "env"
        elif self.signing_secret:
            self._key_origin = "settings"
        else:
            self._key_origin = "missing"
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

    async def deliver(
        self,
        url: str,
        payload: dict,
        event_type: str = "monitor.change",
        max_retries: int = 3,
        retry_delay: float = 5.0,
        record_dead_letter: bool = True,
    ) -> dict[str, Any]:
        """Deliver a webhook with retries.

        Fail-closed: when no signing secret is configured the delivery is
        refused up front (nothing is sent unsigned).
        """
        from pry.api.client import get_client

        # SSRF guard: reject private/loopback/invalid URLs before any network
        # I/O. _validate_url returns a PINNED URL (hostname replaced by the
        # validated IP) so httpx cannot be rebinding-attacked between
        # validation and connect. SNI/Host keep the original hostname for TLS.
        pinned_url, rejection = _validate_url(url)
        if rejection:
            logger.warning("webhook_url_rejected", extra={"url": url, "reason": rejection})
            return {"success": False, "error": f"URL rejected: {rejection}"}

        try:
            ts = str(int(time.time()))
            signature = self.sign_payload(payload, timestamp=ts, event_type=event_type)
        except WebhookSecretNotConfigured as e:
            logger.error(
                "webhook_delivery_refused_unsigned",
                extra={"url": url, "event": event_type},
            )
            return {"success": False, "error": str(e), "refused": True}
        headers = {
            "Content-Type": "application/json",
            "X-Pry-Event": event_type,
            "X-Pry-Signature": f"sha256={signature}",
            "X-Pry-Timestamp": ts,
        }
        # Size the outer cap from the retry budget so the final attempt cannot
        # be cancelled mid-flight: N attempts + all back-off sleeps + slack.
        sleep_budget = sum(retry_delay * (2 ** (i - 1)) for i in range(1, max_retries))
        outer_budget = max_retries * _ATTEMPT_TIMEOUT + sleep_budget + 5.0
        client = await get_client()
        try:
            async with asyncio.timeout(outer_budget):
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = await client.post(
                            pinned_url,
                            json=payload,
                            headers=headers,
                            timeout=_ATTEMPT_TIMEOUT,
                            follow_redirects=False,
                            extensions={"sni_hostname": urllib.parse.urlparse(url).hostname or ""},
                        )
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
                            return {
                                "success": True,
                                "status": resp.status_code,
                                "attempts": attempt,
                            }
                        if resp.status_code < 500:
                            if record_dead_letter:
                                self._dead_letter(
                                    payload, url, f"HTTP {resp.status_code}", event_type
                                )
                            return {
                                "success": False,
                                "status": resp.status_code,
                                "error": "Client error",
                            }
                    except (httpx.HTTPError, httpx.RequestError) as e:
                        logger.warning("webhook_delivery_exception_handler", exc_info=True)
                        record = {
                            "url": url,
                            "attempt": attempt,
                            "error": str(e)[:200],
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                        self._log(record)
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))
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
        items = self.get_dead_letter()
        batch, keep = items[:limit], items[limit:]
        delivered = failed = 0
        for item in batch:
            result = await self.deliver(
                item.get("url", ""),
                item.get("payload", {}),
                event_type=item.get("event", "monitor.change"),
                max_retries=1,
                retry_delay=0.0,
                record_dead_letter=False,
            )
            if result.get("success"):
                delivered += 1
            else:
                failed += 1
                keep.append(item)
        self._write_dead_letter(keep)
        return {
            "total": len(items),
            "attempted": len(batch),
            "delivered": delivered,
            "failed": failed,
            "items": keep,
        }

    def retry_dead_letter(self, limit: int = 20) -> dict[str, Any]:
        """Re-attempt dead-lettered webhooks via the normal signed path.

        Successes are removed from the dead-letter file; failures are kept.
        """
        coro = self._retry_dead_letter_async(limit)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Called from a sync endpoint inside a running loop: run it elsewhere.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
