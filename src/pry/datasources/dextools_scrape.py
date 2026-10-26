# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Dextools scrape orchestration: robots -> render -> normalize -> upsert.

Allowed-path policy is enforced before any network call: a path listed in
robots.txt is a typed ``blocked.robots`` refusal, never a workaround.
"""

from __future__ import annotations

from typing import Any

from pry.datasources.dextools_fetch import fetch_rendered
from pry.datasources.dextools_normalize import normalize_page
from pry.datasources.dextools_robots import robots_verdict
from pry.datasources.dextools_store import DextoolsStore, open_store
from pry.datasources.dextools_types import Refusal

MAX_ROWS_DEFAULT = 200


def scrape_dextools(
    urls: list[str],
    *,
    store: DextoolsStore | None = None,
    renderer: Any = None,
    robots_text: str | None = None,
    limit: int = MAX_ROWS_DEFAULT,
) -> dict[str, Any]:
    """Scrape ``urls`` and upsert normalized rows; returns a one-line-able summary."""
    target = store or open_store()
    fetched = 0
    refused: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for url in urls:
        verdict = robots_verdict(url, robots_text)
        if verdict is not None:
            refused.append(verdict.to_dict())
            continue
        page_html = fetch_rendered(url, renderer=renderer)
        if not isinstance(page_html, str):
            refused.append(page_html.to_dict())
            continue
        fetched += 1
        rows.extend(normalize_page(url, page_html))
        if len(rows) >= limit:
            rows = rows[:limit]
            break

    if fetched and not rows:
        # Never a silent success: an allowed fetch that yielded no data is a block.
        refused.append(
            Refusal(
                code="blocked.measurement",
                reason="allowed pages returned no token data (client-rendered shell, no API path)",
                detail=f"urls={len(urls)}",
            ).to_dict()
        )

    ingested = target.insert(rows)
    return {
        "ingested": ingested,
        "refused": len(refused),
        "total": target.count(),
        "refusals": refused,
    }
