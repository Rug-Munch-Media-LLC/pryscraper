"""Scrape one URL into a validated actor output item."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pry.actors.apify_actor.models import ApifyActorOutput, ApifyScrapeMetadata


async def scrape_url(
    scraper: Any,
    url: str,
    options: dict[str, Any],
) -> ApifyActorOutput:
    """Scrape a single URL and return a validated result.

    Uses ApifyActorOutput for type safety — every emitted field is
    validated by Pydantic.
    """
    start = time.time()
    result = await scraper.scrape(url, options)
    elapsed = round(time.time() - start, 2)

    status = result.get("status", "error")

    if status == "ok":
        content = result.get("content", "")
        return ApifyActorOutput(
            url=url,
            status="ok",
            method=result.get("method", "unknown"),
            scraped_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=elapsed,
            content=content,
            raw_html=result.get("raw_html", ""),
            metadata=ApifyScrapeMetadata(
                domain=urlparse(url).netloc,
                content_length=len(content),
                method=result.get("method", "unknown"),
            ),
        )
    return ApifyActorOutput(
        url=url,
        status="error",
        method=result.get("method", "unknown"),
        scraped_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=elapsed,
        error=result.get("error", "unknown_error"),
    )
