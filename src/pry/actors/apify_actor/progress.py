"""Progress reported to the Apify key-value store."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pry.actors.apify_actor.state import ActorRun


async def report_progress(run: ActorRun) -> None:
    """Publish the counters an Apify operator watches during a run."""
    await run.actor.set_value(
        "STATE",
        {
            "visited": len(run.visited),
            "total_scraped": run.total_scraped,
            "total_errors": run.total_errors,
            "queue_remaining": len(run.to_visit),
        },
    )
