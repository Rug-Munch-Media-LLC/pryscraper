"""Pry — Adaptive Freshness Scheduling.
Conditional scraping, content fingerprinting, staleness dashboard, adaptive frequency."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import hashlib
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

FRESHNESS_DIR = PRY_DATA_DIR / "freshness"
FRESHNESS_DIR.mkdir(parents=True, exist_ok=True)

# ── Content Fingerprinting ──


def compute_content_hash(content: str) -> str:
    """Compute a stable content hash for change detection."""
    normalized = " ".join(content.split())  # Normalize whitespace
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


async def check_content_changed(url: str, content: str) -> dict[str, Any]:
    """Check if content has changed since last scrape using content hash.

    Returns:
        changed: bool — whether content is different from last known
        previous_hash: str — hash of previous content
        current_hash: str — hash of current content
        last_changed: str — ISO timestamp of last detected change
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    fingerprint_path = FRESHNESS_DIR / f"fingerprint_{url_hash}.json"
    current_hash = compute_content_hash(content)

    result: dict[str, Any] = {
        "url": url,
        "current_hash": current_hash,
        "previous_hash": None,
        "changed": True,
        "last_changed": datetime.now(UTC).isoformat(),
        "last_checked": datetime.now(UTC).isoformat(),
        "is_new": True,
    }

    if fingerprint_path.exists():
        try:
            previous = json.loads(fingerprint_path.read_text())
            result["previous_hash"] = previous.get("hash")
            result["last_changed"] = previous.get("last_changed", "")
            result["is_new"] = False
            result["changed"] = current_hash != previous.get("hash")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("freshness_state_load_failed", extra={"error": str(e)[:160]})

    # Save current fingerprint
    with suppress(OSError):
        fingerprint_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "hash": current_hash,
                    "last_checked": result["last_checked"],
                    "last_changed": result["last_changed"],
                }
            )
        )

    return result


async def quick_health_check(url: str) -> dict[str, Any]:
    """Quick HEAD request to check if a URL is responsive without full scrape."""
    from pry.api.client import get_client

    client = await get_client()
    try:
        resp = await client.head(url, timeout=10, follow_redirects=True)
        return {
            "url": url,
            "status_code": resp.status_code,
            "accessible": resp.is_success,
            "content_type": resp.headers.get("content-type", ""),
            "content_length": resp.headers.get("content-length", "0"),
            "last_modified": resp.headers.get("last-modified", ""),
            "etag": resp.headers.get("etag", ""),
        }
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("freshness_suppressed", exc_info=True)
        return {"url": url, "accessible": False, "error": str(e)[:100]}


# ── Adaptive Frequency Calculation ──


def calculate_adaptive_frequency(
    url: str,
    base_interval_minutes: int = 60,
    min_interval: int = 15,
    max_interval: int = 1440,  # 24h
    volatility_window: int = 10,  # Number of checks to look back
) -> dict[str, Any]:
    """Calculate optimal scrape frequency based on content change history.

    Uses a simple Bayesian approach: if content changes frequently,
    increase frequency. If stable, decrease frequency.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    history_path = FRESHNESS_DIR / f"history_{url_hash}.json"

    changes = 0
    total_checks = 0
    change_history: list[bool] = []

    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
            change_history = history.get("changes", [])[-volatility_window:]
            total_checks = len(change_history)
            changes = sum(1 for c in change_history if c)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("freshness_state_load_failed", extra={"error": str(e)[:160]})

    # Store current check
    # (this is called after a scrape, so we record the result)

    # Compute change rate
    change_rate = changes / max(total_checks, 1)

    # Adjust interval
    if change_rate > 0.3:
        # Volatile — increase frequency
        interval = max(min_interval, int(base_interval_minutes * (1 - change_rate)))
    elif change_rate < 0.05 and total_checks >= 5:
        # Very stable — decrease frequency
        interval = min(max_interval, int(base_interval_minutes * 2))
    else:
        interval = base_interval_minutes

    return {
        "url": url,
        "suggested_interval_minutes": interval,
        "change_rate": round(change_rate, 3),
        "total_checks_history": total_checks,
        "changes_detected": changes,
        "volatility": "high" if change_rate > 0.3 else "medium" if change_rate > 0.1 else "low",
        "base_interval": base_interval_minutes,
    }


def record_check_result(url: str, changed: bool) -> None:
    """Record a check result for adaptive frequency calculation."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    history_path = FRESHNESS_DIR / f"history_{url_hash}.json"

    history: dict[str, Any] = {"url": url, "changes": []}
    if history_path.exists():
        with suppress(json.JSONDecodeError, OSError):
            history = json.loads(history_path.read_text())

    history["changes"].append(changed)
    history["last_updated"] = datetime.now(UTC).isoformat()

    # Keep only last 100 entries
    if len(history["changes"]) > 100:
        history["changes"] = history["changes"][-100:]

    with suppress(OSError):
        history_path.write_text(json.dumps(history))


# ── Staleness Dashboard ──


def get_staleness_dashboard() -> dict[str, Any]:
    """Get the staleness dashboard showing all tracked URLs and their freshness."""
    urls: list[dict[str, Any]] = []
    stale_count = 0
    max_age_hours = 24

    for path in FRESHNESS_DIR.glob("fingerprint_*.json"):
        try:
            data = json.loads(path.read_text())
            last_checked = data.get("last_checked", "")
            last_changed = data.get("last_changed", "")
            url = data.get("url", "")

            age_hours = 0.0
            if last_checked:
                try:
                    checked_dt = datetime.fromisoformat(last_checked)
                    age_hours = (datetime.now(UTC) - checked_dt).total_seconds() / 3600
                except (ValueError, TypeError) as e:
                    logger.warning(
                        "freshness_last_checked_parse_failed", extra={"error": str(e)[:160]}
                    )

            is_stale = age_hours > max_age_hours

            urls.append(
                {
                    "url": url[:100],
                    "last_checked": last_checked,
                    "last_changed": last_changed,
                    "age_hours": round(age_hours, 1),
                    "stale": is_stale,
                    "hash": data.get("hash", "")[:12],
                }
            )
            if is_stale:
                stale_count += 1

        except (json.JSONDecodeError, OSError):
            logger.warning("freshness_suppressed", exc_info=True)
            continue

    # Sort by last_checked (oldest first)
    urls.sort(key=lambda x: x.get("age_hours", 0), reverse=True)

    return {
        "total_tracked": len(urls),
        "stale_count": stale_count,
        "fresh_count": len(urls) - stale_count,
        "max_age_hours": max_age_hours,
        "urls": urls[:100],  # Limit to 100
    }
