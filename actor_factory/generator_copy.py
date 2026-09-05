"""— Apify Actor Factory: store copy helpers.

SEO topic phrases, use-case bullets and the actor.json store description.

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec


def _topic(spec: ActorSpec) -> str:
    """Human topic phrase for SEO copy, e.g. 'crypto market monitoring'."""
    t = spec.title.removeprefix("Pry ").lower().replace("-", " ")
    return t


def _use_case_bullets(spec: ActorSpec) -> str:
    """Three domain-relevant use cases (Apify docs: use cases drive conversion)."""
    topic = _topic(spec)
    event = spec.primary_event().name.replace("-", " ")
    return (
        f"- **Continuous monitoring** - schedule the actor to pull fresh "
        f"{topic} data on the cadence you need (hourly, daily, weekly) and "
        "alert via webhooks when anything changes\n"
        f"- **Market & competitive research** - bulk-collect {topic} records "
        "into one dataset to benchmark competitors, prices and trends over "
        "time\n"
        f"- **AI & analytics pipelines** - export clean, structured "
        f"{event} results to JSON/CSV/Excel, or feed them straight into "
        "LLM/RAG workflows, BI dashboards or a warehouse via the Apify API\n"
    )


def _store_description(spec: ActorSpec) -> str:
    """Keyword-rich actor.json description, hard-capped at 200 chars."""
    topic = _topic(spec)
    base = spec.description.strip().rstrip(".")
    tail = f". Scrape, monitor and export {topic} data via API on Apify"
    candidate = base + tail
    if len(candidate) <= 200:
        return candidate
    if len(base) <= 200:
        return base
    cut = base[:197].rsplit(" ", 1)[0]
    return cut + "..."
