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

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from errors import InvalidRequestError
from ultimate_scraper import UltimateScraper
from url_guard import validate_url

logger = logging.getLogger(__name__)

# Apify SDK is imported lazily inside main() so this file doesn't crash
# when imported from the main Pry codebase (where apify isn't installed).


def _extract_links(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from raw HTML for crawling."""
    links: list[str] = []
    parsed_base = urlparse(base_url)
    domain = parsed_base.netloc
    scheme = parsed_base.scheme

    for href in re.findall(r'href=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE):
        link = urljoin(base_url, href)
        link_parsed = urlparse(link)
        if link_parsed.netloc == domain and link_parsed.scheme in ("http", "https"):
            # Deduplicate by removing fragment
            clean = link.split("#")[0]
            if clean not in links:
                links.append(clean)
        elif link.startswith("/"):
            full = f"{scheme}://{domain}{link}"
            if full not in links:
                links.append(full)

    return links[:50]  # cap per page


async def scrape_url(
    scraper: UltimateScraper,
    url: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Scrape a single URL and return a structured result."""
    start = time.time()
    result = await scraper.scrape(url, options)
    elapsed = round(time.time() - start, 2)

    status = result.get("status", "error")
    output: dict[str, Any] = {
        "url": url,
        "status": status,
        "method": result.get("method", "unknown"),
        "scraped_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": elapsed,
    }

    if status == "ok":
        output["content"] = result.get("content", "")
        output["raw_html"] = result.get("raw_html", "")
        output["metadata"] = {
            "domain": urlparse(url).netloc,
            "content_length": len(result.get("content", "") or ""),
            "method": result.get("method", "unknown"),
        }
    else:
        output["error"] = result.get("error", "unknown_error")

    return output


async def main() -> None:
    """Pry Apify Actor entry point."""
    # Lazy import so this file is safe to import from the main codebase.
    from apify import Actor

    async with Actor:
        actor_input = await Actor.get_input() or {}

        # Parse input
        raw_urls = actor_input.get("urls", [])
        if isinstance(raw_urls, str):
            raw_urls = [raw_urls]
        if not raw_urls:
            Actor.log.info("No URLs provided in input; nothing to scrape.")
            await Actor.push_data({"status": "skipped", "reason": "no_urls"})
            return

        max_pages = max(1, int(actor_input.get("max_pages", 1)))
        timeout = int(actor_input.get("timeout", 30))
        output_format = actor_input.get("output_format", "markdown")
        crawl = bool(actor_input.get("crawl", False))

        # Build scraper options
        base_options: dict[str, Any] = {
            "timeout": timeout,
        }
        if actor_input.get("proxy_config", {}).get("use_apify_proxies"):
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
        to_visit: list[str] = list(raw_urls)
        total_scraped = 0
        total_errors = 0

        Actor.log.info(
            "pry_actor_start",
            extra={
                "urls": len(raw_urls),
                "max_pages": max_pages,
                "crawl": crawl,
                "timeout": timeout,
            },
        )

        while to_visit and total_scraped < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            # Validate URL before scraping
            try:
                validate_url(url)
            except InvalidRequestError as e:
                Actor.log.warning("pry_actor_skip_invalid", extra={"url": url, "error": str(e)})
                await Actor.push_data(
                    {
                        "url": url,
                        "status": "error",
                        "error": f"Invalid URL: {e}",
                        "scraped_at": datetime.now(UTC).isoformat(),
                    }
                )
                total_errors += 1
                continue

            # Scrape with options
            Actor.log.info("pry_actor_scrape", extra={"url": url, "remaining": len(to_visit)})
            options = dict(base_options)
            if output_format:
                options["output_format"] = output_format

            output = await scrape_url(scraper, url, options)

            # For crawled URLs, try to extract more links
            if crawl and output["status"] == "ok":
                html = output.get("raw_html", "")
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

            await Actor.push_data(output)
            total_scraped += 1
            if output["status"] != "ok":
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
