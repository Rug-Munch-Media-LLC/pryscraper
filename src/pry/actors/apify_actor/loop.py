"""The crawl loop itself."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

from pry.actors.apify_actor.step import scrape_step

if TYPE_CHECKING:
    from pry.actors.apify_actor.state import ActorRun


def _log_finish(run: ActorRun) -> None:
    """Summarise the run for the Apify log."""
    run.actor.log.info(
        "pry_actor_finish",
        extra={
            "total_scraped": run.total_scraped,
            "total_errors": run.total_errors,
            "urls_visited": len(run.visited),
        },
    )


async def run_loop(run: ActorRun) -> None:
    """Drain the frontier until it is empty or ``max_pages`` is reached."""
    while run.to_visit and run.total_scraped < run.validated.max_pages:
        await scrape_step(run)
    _log_finish(run)
