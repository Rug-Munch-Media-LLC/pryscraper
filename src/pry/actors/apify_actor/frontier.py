"""Crawl-frontier expansion from a scraped page."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

from pry.actors.apify_actor.links import _extract_links

if TYPE_CHECKING:
    from pry.actors.apify_actor.state import ActorRun

MAX_NEW_LINKS_PER_PAGE = 20


def enqueue_discovered(run: ActorRun, url: str, html: str) -> None:
    """Add this page's unseen same-domain links to the queue, capped per page."""
    discovered = _extract_links(html, url)
    new_links = [
        link for link in discovered if link not in run.visited and link not in run.to_visit
    ]
    run.to_visit.extend(new_links[:MAX_NEW_LINKS_PER_PAGE])
    run.actor.log.debug(
        "pry_actor_links_discovered",
        extra={"url": url, "new_links": len(new_links)},
    )
