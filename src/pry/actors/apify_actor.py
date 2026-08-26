"""Pry Apify Actor — web scraping + browser automation on the Apify platform.

Runs Pry's multi-tier scraper (UltimateScraper) as an Apify actor.
Accepts a list of URLs, scrapes each one through up to 12 fallback tiers,
and pushes the results (markdown content + metadata) to the Apify dataset.

Usage:
    Deploy to Apify Console or run locally with:
        apify run -p

Input (JSON):
    {
        "urls": ["https://example.com", ...],
        "max_pages": 1,
        "timeout": 30,
        "output_format": "markdown",
        "proxy_config": {
            "use_apify_proxies": true,
            "proxy_country": "US"
        }
    }

Output (dataset items):
    {
        "url": "https://example.com",
        "status": "ok" | "error",
        "content": "...markdown or html...",
        "method": "direct" | "flaresolverr" | ...,
        "metadata": {
            "title": "...",
            "description": "...",
            "domain": "example.com",
            "scraped_at": "2026-07-03T..."
        }
    }
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator

from pry.core.errors import InvalidRequestError
from pry.engine.ultimate_scraper import UltimateScraper
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)

# Apify SDK is imported lazily inside main() so this file doesn't crash
# when imported from the main Pry codebase (where apify isn't installed).


# ── Pydantic input/output models (T1 win #3: Pydantic for Apify) ─────────────


class ApifyProxyConfig(BaseModel):
    """Proxy configuration for the Apify actor."""

    use_apify_proxies: bool = Field(
        default=False,
        description="Use Apify-provided residential proxies",
    )
    proxy_country: str = Field(
        default="US",
        description="Country code for proxy geolocation (e.g., 'US', 'DE')",
        min_length=2,
        max_length=2,
    )


class ApifyActorInput(BaseModel):
    """Validated input for the Pry Apify actor.

    Replaces raw dict access with Pydantic validation — catches malformed
    input before any scraping starts.
    """

    urls: list[str] = Field(
        ...,
        description="List of URLs to scrape",
        min_length=1,
        max_length=1000,
    )
    max_pages: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Maximum number of pages to scrape (1-1000)",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout per URL in seconds (5-120)",
    )
    output_format: str = Field(
        default="markdown",
        description="Output format",
        pattern=r"^(markdown|html|text|json)$",
    )
    crawl: bool = Field(
        default=False,
        description="Follow same-domain links and crawl",
    )
    proxy_config: ApifyProxyConfig = Field(
        default_factory=ApifyProxyConfig,
        description="Proxy configuration",
    )
    max_depth: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum crawl depth (0-5)",
    )

    @field_validator("urls", mode="before")
    @classmethod
    def coerce_urls(cls, v: Any) -> list[str]:
        """Accept a single URL string and coerce to list."""
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("urls", mode="before")
    @classmethod
    def validate_urls(cls, v: Any) -> list[str]:
        """Strip whitespace and filter empty strings."""
        if isinstance(v, list):
            return [url.strip() for url in v if isinstance(url, str) and url.strip()]
        return v


class ApifyScrapeMetadata(BaseModel):
    """Metadata attached to a successful scrape result."""

    domain: str = Field(..., description="Scraped domain")
    content_length: int = Field(..., ge=0, description="Content length in characters")
    method: str = Field(default="unknown", description="Scraping method used")


class ApifyActorOutput(BaseModel):
    """Validated output pushed to the Apify dataset.

    T1 win #4: Structured output schema — Apify customers depend on this
    contract; Pydantic ensures every emitted item conforms.
    """

    url: str = Field(..., description="Original URL scraped")
    status: str = Field(
        ...,
        description="Result status",
        pattern=r"^(ok|error|skipped)$",
    )
    method: str = Field(default="unknown", description="Scraping method used")
    scraped_at: str = Field(..., description="ISO-8601 timestamp of scrape")
    elapsed_seconds: float = Field(default=0.0, ge=0, description="Time spent scraping")
    content: str = Field(default="", description="Scraped content (markdown/html/text)")
    raw_html: str = Field(default="", description="Raw HTML (if available)")
    error: str = Field(default="", description="Error message (if status=error)")
    metadata: ApifyScrapeMetadata = Field(
        default_factory=lambda: ApifyScrapeMetadata(
            domain="unknown", content_length=0, method="unknown"
        ),
        description="Scraping metadata",
    )

    def to_dataset_item(self) -> dict[str, Any]:
        """Convert to Apify dataset item dict (excludes None/empty fields)."""
        return self.model_dump(mode="json", exclude_none=True)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from raw HTML for crawling.

    Handles absolute URLs AND root-relative hrefs (``/path``) - the latter
    are the majority on real sites and were previously dropped entirely,
    crippling crawl mode (the old relative branch was unreachable because
    the only regex matched absolute URLs).
    """
    links: list[str] = []
    parsed_base = urlparse(base_url)
    domain = parsed_base.netloc

    hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    hrefs += re.findall(r'href=["\'](/[^"\']*)["\']', html, re.IGNORECASE)

    for href in hrefs:
        link = urljoin(base_url, href)
        link_parsed = urlparse(link)
        if link_parsed.netloc == domain and link_parsed.scheme in ("http", "https"):
            clean = link.split("#")[0]
            if clean not in links:
                links.append(clean)

    return links[:50]  # cap per page


async def scrape_url(
    scraper: UltimateScraper,
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


async def _push_with_retry(
    actor: Any,
    data: ApifyActorOutput,
    max_retries: int = 3,
) -> None:
    """Push data to Apify dataset with exponential backoff retry.

    T1 win #22: Don't lose data on transient network errors.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            await actor.push_data(data.to_dataset_item())
            return
        except (OSError, RuntimeError, TimeoutError) as e:
            last_error = e
            wait = min(2**attempt, 10)
            logger.warning(
                "apify_push_retry",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "wait": wait,
                    "error": str(e),
                },
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
    logger.error("apify_push_failed", extra={"error": str(last_error)})


async def main() -> None:
    """Pry Apify Actor entry point."""
    # Lazy import so this file is safe to import from the main codebase.
    from apify import Actor

    async with Actor:
        raw_input = await Actor.get_input() or {}

        # T1 win #3: Pydantic input validation — catch malformed input early
        try:
            validated = ApifyActorInput.model_validate(raw_input)
        except ValidationError as e:
            Actor.log.error("pry_actor_input_invalid", extra={"error": str(e)})
            await _push_with_retry(
                Actor,
                ApifyActorOutput(
                    url="",
                    status="error",
                    error=f"Invalid input: {e}",
                    scraped_at=datetime.now(UTC).isoformat(),
                ),
            )
            return

        # Build scraper options
        base_options: dict[str, Any] = {
            "timeout": validated.timeout,
        }
        if validated.proxy_config.use_apify_proxies:
            # Apify provides HTTP proxies via http://user:pass@proxy.apify.com:8000
            # Actor.config was removed in apify SDK 3.x — build the URL from
            # Actor.configuration instead (proxy_hostname/proxy_port/proxy_password).
            configuration = Actor.configuration
            proxy_password = configuration.proxy_password
            if proxy_password:
                proxy_url = (
                    f"http://auto:{proxy_password}"
                    f"@{configuration.proxy_hostname}:{configuration.proxy_port}"
                )
                base_options["proxy_url"] = proxy_url

        scraper = UltimateScraper()
        visited: set[str] = set()
        to_visit: list[str] = list(validated.urls)
        total_scraped = 0
        total_errors = 0

        Actor.log.info(
            "pry_actor_start",
            extra={
                "urls": len(validated.urls),
                "max_pages": validated.max_pages,
                "crawl": validated.crawl,
                "timeout": validated.timeout,
            },
        )

        while to_visit and total_scraped < validated.max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            # Validate URL before scraping
            try:
                validate_url(url)
            except InvalidRequestError as e:
                Actor.log.warning("pry_actor_skip_invalid", extra={"url": url, "error": str(e)})
                await _push_with_retry(
                    Actor,
                    ApifyActorOutput(
                        url=url,
                        status="error",
                        error=f"Invalid URL: {e}",
                        scraped_at=datetime.now(UTC).isoformat(),
                    ),
                )
                total_errors += 1
                continue

            # Scrape with options
            Actor.log.info("pry_actor_scrape", extra={"url": url, "remaining": len(to_visit)})
            options = dict(base_options)
            options["output_format"] = validated.output_format

            output = await scrape_url(scraper, url, options)

            # For crawled URLs, try to extract more links
            if validated.crawl and output.status == "ok":
                html = output.raw_html
                if html:
                    discovered = _extract_links(html, url)
                    new_links = [
                        link for link in discovered if link not in visited and link not in to_visit
                    ]
                    to_visit.extend(new_links[:20])  # cap frontier per page
                    Actor.log.debug(
                        "pry_actor_links_discovered",
                        extra={"url": url, "new_links": len(new_links)},
                    )

            await _push_with_retry(Actor, output)
            total_scraped += 1
            if output.status != "ok":
                total_errors += 1

            # Report progress to Apify
            await Actor.set_value(
                "STATE",
                {
                    "visited": len(visited),
                    "total_scraped": total_scraped,
                    "total_errors": total_errors,
                    "queue_remaining": len(to_visit),
                },
            )

        Actor.log.info(
            "pry_actor_finish",
            extra={
                "total_scraped": total_scraped,
                "total_errors": total_errors,
                "urls_visited": len(visited),
            },
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
