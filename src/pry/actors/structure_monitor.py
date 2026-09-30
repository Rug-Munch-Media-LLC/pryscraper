"""Pry — Page Structure Monitor.
Track CSS selector validity over time. Alert before scrapers break."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from lxml import html as lxml_html

from pry.api.client import get_client
from pry.core.db import StructureSnapshot, session_scope
from pry.core.errors import PryError
from pry.engine.fetch_guard import guard_get

logger = logging.getLogger(__name__)

#: Browser-shaped UA: the pages these selectors run against often serve markup
#: only to a browser. ``guard_get`` takes it as a parameter (never ``follow_redirects``).
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (StructureMonitor/1.0)"


async def check_selectors(
    url: str,
    selectors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check if CSS selectors still match on a page.

    Args:
        url: The URL to check
        selectors: List of selector dicts with name, selector, and type fields

    Returns per-selector match status with similarity score.
    """
    result: dict[str, Any] = {
        "url": url,
        "checked_at": datetime.now(UTC).isoformat(),
        "selectors": [],
        "all_matched": True,
        "matched_count": 0,
        "failed_count": 0,
    }

    try:
        client = await get_client()
        resp = await guard_get(client, url, timeout=30, user_agent=_UA)
        if not resp.is_success:
            return {"url": url, "error": f"HTTP {resp.status_code}", "all_matched": False}
        html_content = resp.text
    except (httpx.HTTPError, httpx.RequestError, PryError) as e:
        return {"url": url, "error": str(e)[:200], "all_matched": False}

    try:
        tree = lxml_html.fromstring(html_content)
    except Exception:  # noqa: BLE001
        return {"url": url, "error": "Failed to parse HTML", "all_matched": False}

    for sel in selectors:
        selector_str = sel.get("selector", "")
        name = sel.get("name", selector_str[:30])
        sel_type = sel.get("type", "css")

        try:
            if sel_type == "css":
                elements = tree.cssselect(selector_str)
            elif sel_type == "xpath":
                elements = tree.xpath(selector_str)
            else:
                elements = []

            match_count = len(elements)
            is_matched = match_count > 0

            selector_result: dict[str, Any] = {
                "name": name,
                "selector": selector_str,
                "type": sel_type,
                "matched": is_matched,
                "match_count": match_count,
                "status": "ok" if is_matched else "broken",
            }

            if is_matched and elements:
                sample_text = " ".join(e.text_content().strip()[:100] for e in elements[:3])
                selector_result["sample"] = sample_text[:200]

            result["selectors"].append(selector_result)
            if is_matched:
                result["matched_count"] += 1
            else:
                result["failed_count"] += 1

        except Exception as e:  # noqa: BLE001
            result["selectors"].append(
                {
                    "name": name,
                    "selector": selector_str,
                    "type": sel_type,
                    "matched": False,
                    "match_count": 0,
                    "status": "error",
                    "error": str(e)[:100],
                }
            )
            result["failed_count"] += 1

    result["all_matched"] = result["failed_count"] == 0
    return result


def _persist_snapshot(
    url: str,
    url_hash: str,
    template_id: str,
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare against history and store a new snapshot.

    Runs entirely in a worker thread — the sync session is opened, used, and
    closed inside this call so no sync connection is held across an ``await``.
    Returns the list of detected changes.
    """
    with session_scope() as s:
        if template_id:
            previous_snap = (
                s.query(StructureSnapshot)
                .filter(StructureSnapshot.template_id == template_id)
                .order_by(StructureSnapshot.checked_at.desc())
                .first()
            )
        else:
            previous_snap = (
                s.query(StructureSnapshot)
                .filter(StructureSnapshot.url_hash == url_hash)
                .order_by(StructureSnapshot.checked_at.desc())
                .first()
            )

        previous_selectors: list[Any]
        if previous_snap:
            raw_selectors = previous_snap.selectors
            previous_selectors = raw_selectors if isinstance(raw_selectors, list) else []
            previous_all_matched = (
                bool(previous_snap.all_matched)
                if isinstance(previous_snap.all_matched, bool)
                else True
            )
        else:
            previous_selectors = []
            previous_all_matched = True

        changes: list[dict[str, Any]] = []
        prev_map = {s["name"]: s for s in previous_selectors if isinstance(s, dict)}
        curr_map = {s["name"]: s for s in current.get("selectors", []) if isinstance(s, dict)}

        for name, curr_sel in curr_map.items():
            prev_sel = prev_map.get(name)
            if prev_sel:
                if prev_sel.get("matched") and not curr_sel.get("matched"):
                    changes.append(
                        {
                            "type": "selector_broken",
                            "severity": "critical",
                            "name": name,
                            "selector": curr_sel.get("selector", ""),
                            "message": f"CSS selector '{name}' stopped matching (was matching before)",
                        }
                    )
                elif not prev_sel.get("matched") and curr_sel.get("matched"):
                    changes.append(
                        {
                            "type": "selector_fixed",
                            "severity": "info",
                            "name": name,
                            "message": f"CSS selector '{name}' started matching again",
                        }
                    )
                elif curr_sel.get("match_count") != prev_sel.get("match_count"):
                    changes.append(
                        {
                            "type": "count_changed",
                            "severity": "medium",
                            "name": name,
                            "message": f"Selector '{name}' matched {prev_sel.get('match_count')} elements before, now {curr_sel.get('match_count')}",
                            "previous_count": prev_sel.get("match_count"),
                            "current_count": curr_sel.get("match_count"),
                        }
                    )

        if previous_selectors and previous_all_matched and not current.get("all_matched"):
            changes.append(
                {
                    "type": "structure_broken",
                    "severity": "critical",
                    "name": "page_structure",
                    "message": f"Page structure changed — {current.get('failed_count')} selectors now fail",
                    "failed_selectors": [
                        s["name"] for s in current.get("selectors", []) if not s.get("matched")
                    ],
                }
            )

        now = datetime.now(UTC)
        snapshot = StructureSnapshot(
            url=url,
            url_hash=url_hash,
            template_id=template_id,
            selectors=current.get("selectors", []),
            all_matched=current.get("all_matched", False),
            matched_count=current.get("matched_count", 0),
            failed_count=current.get("failed_count", 0),
            changes=changes,
            change_count=len(changes),
            has_changes=len(changes) > 0,
            dom_summary={},
            checked_at=now,
        )
        s.add(snapshot)
        return changes


async def monitor_page_structure(
    url: str,
    selectors: list[dict[str, Any]],
    template_id: str = "",
) -> dict[str, Any]:
    """Monitor page structure by checking selectors and comparing to history.

    Returns the current check result plus any detected changes since last check.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

    current = await check_selectors(url, selectors)
    if "error" in current:
        return current

    try:
        changes = await asyncio.to_thread(_persist_snapshot, url, url_hash, template_id, current)
    except Exception:
        logger.exception("structure_monitor_save_failed", extra={"url": url})
        changes = []

    current["changes"] = changes
    current["change_count"] = len(changes)
    current["has_changes"] = len(changes) > 0
    current["template_id"] = template_id
    current["url_hash"] = url_hash

    return current


def _fetch_history(url: str, template_id: str) -> dict[str, Any]:
    """Fetch the latest structure snapshot. Runs in a worker thread."""
    with session_scope() as s:
        if template_id:
            snap = (
                s.query(StructureSnapshot)
                .filter(StructureSnapshot.template_id == template_id)
                .order_by(StructureSnapshot.checked_at.desc())
                .first()
            )
        else:
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            snap = (
                s.query(StructureSnapshot)
                .filter(StructureSnapshot.url_hash == url_hash)
                .order_by(StructureSnapshot.checked_at.desc())
                .first()
            )

        if not snap:
            return {"url": url, "has_history": False}

        return {
            "url": url,
            "has_history": True,
            "last_checked": snap.checked_at.isoformat() if snap.checked_at else "",
            "last_all_matched": snap.all_matched,
            "last_selectors": snap.selectors or [],
        }


async def get_structure_history(url: str, template_id: str = "") -> dict[str, Any]:
    """Get structure check history for a URL."""
    try:
        return await asyncio.to_thread(_fetch_history, url, template_id)
    except Exception:
        logger.exception("structure_history_fetch_failed", extra={"url": url})
        return {"url": url, "has_history": False}
