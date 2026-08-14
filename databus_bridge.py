"""Pry — DataBus Bridge: publish scrape results to rmi-backend for ingest.

Registered as a pipeline hook at "before_return". After scraping completes,
the hook POSTs the result to the RMI backend's DataBus ingest endpoint.

Design:
  - Fire-and-forget: failure to publish does NOT affect the scrape result
  - Retry queue: failed deliveries are retried with exponential backoff
  - No synchronous dependency: if backend is down, pryscraper stores locally as usual
  - Configurable via env vars: PRY_DATABUS_URL, PRY_DATABUS_ENABLED

Usage:
    from databus_bridge import register_databus_bridge
    register_databus_bridge(pipeline)

Or set PRY_DATABUS_ENABLED=1 to auto-register on import.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from paths import PRY_DATA_DIR
from pipeline import Pipeline, get_pipeline

# Use structlog if available for structured logging with extra kwargs
try:
    import structlog

    logger = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────
DATABUS_URL = os.getenv(
    "PRY_DATABUS_URL",
    "http://rmi-backend:8000/api/v1/databus/ingest",
)
DATABUS_ENABLED = os.getenv("PRY_DATABUS_ENABLED", "1") == "1"
DATABUS_TIMEOUT = int(os.getenv("PRY_DATABUS_TIMEOUT", "10"))
DATABUS_MAX_RETRIES = int(os.getenv("PRY_DATABUS_MAX_RETRIES", "3"))

# Retry queue (persistent on disk for durability)
RETRY_DIR = PRY_DATA_DIR / "databus_retry"
RETRY_DIR.mkdir(parents=True, exist_ok=True)


# ── Bridge hook — called by pipeline at "before_return" ─────────────


async def publish_to_databus(**kwargs: Any) -> dict[str, Any]:
    """Pipeline hook: publish scraped results to the DataBus ingest endpoint.

    This hook is registered on the global pipeline at "before_return".
    It POSTs the scraped data to rmi-backend for storage, RAG indexing,
    and downstream consumption.

    Returns an empty dict (does not modify the pipeline context).
    """
    if not DATABUS_ENABLED:
        return {}

    # Extract relevant fields from the pipeline context
    url = kwargs.get("url", "")
    content = kwargs.get("content", {})
    status = kwargs.get("status", "")
    data_type = _classify_scrape(kwargs)

    # Only publish successful scrapes with content
    if status != "ok" or not content:
        return {}

    # Build the payload
    payload = {
        "source": "pryscraper",
        "data_type": data_type,
        "content": _extract_content(kwargs),
        "url": url,
        "token_address": _extract_address(url, content),
        "chain": _extract_chain(kwargs),
        "scraped_at": datetime.now(UTC).isoformat(),
    }

    # Fire-and-forget: publish in background, never block the pipeline
    asyncio.ensure_future(_deliver_with_retry(payload))

    return {}


def _classify_scrape(context: dict[str, Any]) -> str:
    """Classify the scrape result into a DataBus data_type.

    Heuristic-based classification for high-value data types.
    Falls back to "scraped_intel" for general web scraping.
    """
    url = context.get("url", "").lower()
    title = (context.get("title") or "").lower()

    # Scam detection / rugpull reports
    scam_signals = [
        "scam",
        "rug",
        "honeypot",
        "fraud",
        "phishing",
        "suspicious",
        "malicious",
        "fake",
        "ponzi",
    ]
    if any(s in url or s in title for s in scam_signals):
        return "scam_report"

    # Threat intelligence
    threat_signals = [
        "threat",
        "exploit",
        "vulnerability",
        "attack",
        "breach",
        "hack",
        "malware",
        "cve-",
    ]
    if any(s in url or s in title for s in threat_signals):
        return "threat_intel"

    # Blockchain / token data
    blockchain_signals = [
        "token",
        "contract",
        "blockchain",
        "defi",
        "liquidity",
        "pool",
        "swap",
        "dex",
    ]
    if any(s in url or s in title for s in blockchain_signals):
        return "blockchain_data"

    # Entity profiling
    entity_signals = [
        "wallet",
        "address",
        "entity",
        "profile",
        "portfolio",
        "holder",
    ]
    if any(s in url or s in title for s in entity_signals):
        return "entity_profile"

    return "scraped_intel"


def _extract_content(context: dict[str, Any]) -> dict[str, Any]:
    """Extract a clean, serializable content dict from the pipeline context."""
    return {
        "title": context.get("title", ""),
        "description": context.get("description", ""),
        "content_preview": (context.get("content") or "")[:5000],
        "quality_score": context.get("quality_score", 0),
        "method": context.get("method", ""),
        "extracted_links": context.get("extracted_links", []),
        "raw_data": context.get("data", {}),
    }


def _extract_address(url: str, content: Any) -> str:
    """Try to extract a blockchain address from URL or content."""
    import re

    # Solana address (base58, 32-44 chars)
    sol_match = re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", url)
    if sol_match:
        return sol_match.group(0)

    # EVM address (0x + 40 hex chars)
    evm_match = re.search(r"0x[a-fA-F0-9]{40}", url)
    if evm_match:
        return evm_match.group(0)

    # Check content for first relevant address
    if isinstance(content, dict):
        text = str(content.get("content_preview", ""))
    else:
        text = str(content)[:2000]

    sol_match = re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
    if sol_match:
        return sol_match.group(0)
    evm_match = re.search(r"0x[a-fA-F0-9]{40}", text)
    if evm_match:
        return evm_match.group(0)

    return ""


def _extract_chain(context: dict[str, Any]) -> str:
    """Try to determine the blockchain chain from context."""
    url = context.get("url", "").lower()
    content = (context.get("content") or "").lower()

    chain_map = {
        "solana": ["solana", "solscan", "spl"],
        "ethereum": ["ethereum", "etherscan", "eth"],
        "bsc": ["bsc", "bscscan", "binance"],
        "base": ["base", "basescan"],
        "polygon": ["polygon", "polygonscan", "matic"],
        "arbitrum": ["arbitrum", "arbiscan"],
        "tron": ["tron", "tronscan", "trx"],
    }

    for chain, signals in chain_map.items():
        if any(s in url or s in content for s in signals):
            return chain

    return ""


# ── Delivery with retry queue ──────────────────────────────────────


async def _deliver_with_retry(payload: dict[str, Any], attempt: int = 1) -> bool:
    """Post to DataBus with retry on failure.

    Retries with exponential backoff (2^attempt seconds).
    Writes to a persistent file queue if retries exhausted.
    """
    for a in range(1, DATABUS_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DATABUS_TIMEOUT) as client:
                resp = await client.post(DATABUS_URL, json=payload)
                if resp.is_success:
                    logger.info(
                        "databus_published",
                        data_type=payload.get("data_type"),
                        url=str(payload.get("url", ""))[:60],
                        status=resp.status_code,
                    )
                    return True

                # Non-retryable client error
                if resp.status_code < 500:
                    logger.warning(
                        "databus_rejected",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False

        except (httpx.RequestError, httpx.HTTPError, OSError, TimeoutError) as e:
            logger.warning(
                "databus_retry",
                attempt=a,
                error=str(e)[:100],
                max_retries=DATABUS_MAX_RETRIES,
            )

        if a < DATABUS_MAX_RETRIES:
            await asyncio.sleep(2**a)  # exponential backoff

    # Exhausted retries — persist to disk queue for later delivery
    _queue_for_retry(payload)
    return False


def _queue_for_retry(payload: dict[str, Any]) -> None:
    """Persist failed payload to disk for retry by the retry consumer."""
    retry_path = RETRY_DIR / f"retry_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.json"
    try:
        retry_path.write_text(
            json.dumps(
                {
                    "payload": payload,
                    "queued_at": datetime.now(UTC).isoformat(),
                    "retry_count": DATABUS_MAX_RETRIES,
                },
                default=str,
            )
        )
        logger.info("databus_queued_for_retry", path=str(retry_path))
    except OSError as e:
        logger.error("databus_retry_queue_failed", error=str(e)[:200])


# ── Retry consumer (call from cron or at startup) ──────────────────


async def process_retry_queue() -> dict[str, int]:
    """Re-process all queued payloads.

    Call this at startup or periodically to drain the retry queue.
    Returns stats: {processed, succeeded, failed, remaining}.
    """
    if not RETRY_DIR.exists():
        return {"processed": 0, "succeeded": 0, "failed": 0, "remaining": 0}

    processed = 0
    succeeded = 0
    failed = 0

    for path in sorted(RETRY_DIR.glob("retry_*.json")):
        try:
            data = json.loads(path.read_text())
            payload = data.get("payload", {})
            if payload:
                ok = await _deliver_with_retry(payload)
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                path.unlink()  # remove regardless (avoid infinite retry loop)
                processed += 1
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("retry_queue_read_failed", path=str(path), error=str(e)[:100])
            failed += 1

    remaining = len(list(RETRY_DIR.glob("retry_*.json")))
    logger.info(
        "databus_retry_queue_processed",
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        remaining=remaining,
    )
    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "remaining": remaining,
    }


# ── Registration helper ────────────────────────────────────────────


def register_databus_bridge(pipeline: Pipeline | None = None) -> None:
    """Register the databus bridge hook on the pipeline.

    Call once at app startup:
        from databus_bridge import register_databus_bridge
        register_databus_bridge()
    """
    if not DATABUS_ENABLED:
        logger.info("databus_bridge_disabled (set PRY_DATABUS_ENABLED=1 to enable)")
        return

    p = pipeline or get_pipeline()
    p.register("before_return", publish_to_databus, priority=50)
    logger.info(
        "databus_bridge_registered",
        url=DATABUS_URL.split("@")[-1] if "@" in DATABUS_URL else DATABUS_URL,
    )


# ── Auto-register on import (optional) ─────────────────────────────

# When this module is imported and DATABUS_ENABLED is set, auto-register
# the hook on the global pipeline singleton. This makes integration
# zero-config for existing Pry deployments.
if DATABUS_ENABLED:
    try:
        register_databus_bridge()
    except Exception as exc:  # noqa: BLE001 - auto-register must never crash import
        logger.warning("databus_bridge_auto_register_failed", error=str(exc)[:100])
