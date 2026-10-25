"""One iteration of the crawl loop: pop, scrape, push."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pry.actors.apify_actor.frontier import enqueue_discovered
from pry.actors.apify_actor.models import ApifyActorOutput
from pry.actors.apify_actor.progress import report_progress
from pry.actors.apify_actor.push import _push_with_retry
from pry.actors.apify_actor.scrape import scrape_url
from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

if TYPE_CHECKING:
    from pry.actors.apify_actor.state import ActorRun


def _options(run: ActorRun) -> dict[str, Any]:
    """Per-URL scraper options: the run defaults plus the requested format."""
    options = dict(run.base_options)
    options["output_format"] = run.validated.output_format
    return options


async def _push_rejected_url(run: ActorRun, url: str, error: InvalidRequestError) -> None:
    """Report a URL the guard refused, then let the run continue."""
    run.actor.log.warning("pry_actor_skip_invalid", extra={"url": url, "error": str(error)})
    await _push_with_retry(
        run.actor,
        ApifyActorOutput(
            url=url,
            status="error",
            error=f"Invalid URL: {error}",
            scraped_at=datetime.now(UTC).isoformat(),
        ),
    )
    run.total_errors += 1


async def scrape_step(run: ActorRun) -> None:
    """Scrape the next queued URL and record its result on the run."""
    url = run.to_visit.pop(0)
    if url in run.visited:
        return
    run.visited.add(url)

    try:
        validate_url(url)
    except InvalidRequestError as e:
        await _push_rejected_url(run, url, e)
        return

    run.actor.log.info("pry_actor_scrape", extra={"url": url, "remaining": len(run.to_visit)})
    output = await scrape_url(run.scraper, url, _options(run))

    if run.validated.crawl and output.status == "ok" and output.raw_html:
        enqueue_discovered(run, url, output.raw_html)

    await _push_with_retry(run.actor, output)
    run.total_scraped += 1
    if output.status != "ok":
        run.total_errors += 1
    await report_progress(run)
