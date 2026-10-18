"""Pry - Apify Actor Factory: pay-per-event runtime.

Implements the monetization patterns from Apify's PPE documentation
(docs.apify.com/actors/publishing/monetize/pay-per-event) as a reusable
runner so every factory-generated actor bills correctly:

- Charge per result via ``push_data(item, charged_event_name=...)`` (charge
  + save in one platform call; error items are charged too - work done is
  billed).
- Stop gracefully when ``event_charge_limit_reached`` is true (user
  spending limit), per docs "finish the run once charges reach the limit".
- Register an ABORTING handler that flushes completed-but-unbilled work
  inside the 30-second graceful-shutdown window.
- Never manually charge synthetic events (apify-actor-start /
  apify-default-dataset-item) - the platform bills those automatically.

The Actor SDK is imported lazily and can be fully replaced by a mock, so
the entire billing behaviour is testable without the apify package.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from actor_factory.abuse_guard import AbuseGuard
from actor_factory.runner_billing import BillingMixin
from actor_factory.runner_flow import CrawlCtx, FlowMixin
from actor_factory.runner_types import ActorLike, ActorRunConfig, RunPlan, RunStats

logger = logging.getLogger(__name__)

__all__ = ["ActorLike", "ActorRunConfig", "PPEScraperRunner", "RunPlan", "RunStats"]


def _load_actor() -> Any:
    """Import the real Actor SDK lazily (absent in unit-test environments)."""
    from apify import Actor

    return Actor


class PPEScraperRunner(BillingMixin, FlowMixin):
    """Shared PPE run loop for all Pry factory actors.

    Subclasses (or tests) override :meth:`process_url` to map one input URL
    to a dataset item; the runner handles charging, limits, aborts.
    """

    def __init__(self, config: ActorRunConfig, actor_module: Any = None):
        self.config = config
        self._actor_module = actor_module
        self.stats = RunStats()
        self._pending: list[dict[str, Any]] = []

    # -- Actor access -------------------------------------------------------

    def actor(self) -> Any:
        if self._actor_module is not None:
            return self._actor_module
        return _load_actor()

    # -- Item production ----------------------------------------------------

    async def process_url(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
        """Produce ONE dataset item for one URL.

        Default implementation drives Pry's UltimateScraper directly.
        Override for specialised actors (screenshots, monitors, ...).
        """
        from pry.engine.ultimate_scraper import UltimateScraper

        scraper = getattr(self, "_scraper", None)
        if scraper is None:
            scraper = UltimateScraper()
            self._scraper = scraper
        result = await scraper.scrape(url, options)
        item: dict[str, Any] = {
            "url": url,
            "status": result.get("status", "error"),
            "method": result.get("method", "unknown"),
            "scraped_at": datetime.now(UTC).isoformat(),
        }
        if result.get("status") == "ok":
            item["content"] = result.get("content", "")
            item["metadata"] = {
                "domain": url.split("/")[2] if "://" in url else url,
                "content_length": len(result.get("content") or ""),
                "method": result.get("method", "unknown"),
            }
        else:
            item["error"] = result.get("error", "unknown_error")
        return item

    # -- Charging helpers ---------------------------------------------------

    # -- Main loop ----------------------------------------------------------

    async def run(self) -> RunStats:
        actor = self.actor()
        async with actor:
            actor.on("aborting", self.on_aborting)
            raw_input = await actor.get_input() or {}
            plan = self._plan(raw_input)
            state: dict[str, Any] = {}
            guard = AbuseGuard(
                skip_counts_as_failure=self.config.processor_name != "monitor",
            )
            queue: list[tuple[str, int]] = [
                (u, 0) for u in plan.urls[: self.config.max_items]
            ]
            seen: set[str] = {u for u, _ in queue}
            state["depths"] = dict(queue)
            processed = 0
            while queue and processed < self.config.max_items:
                url, depth = queue.pop(0)
                processed += 1
                if guard.tripped and await self._handle_trip(actor, guard):
                    break
                item = await self._process(url, plan.options, state)
                ctx = CrawlCtx(depth, seen, queue, state["depths"])
                if self._should_expand(item, ctx, plan):
                    self._expand(item, url, ctx, plan)
                guard.record(item.get("status", "error"), url)
                if not await self.push_and_charge(actor, item):
                    logger.warning(
                        "ppe_user_limit_reached",
                        extra={"processed": self.stats.pushed_ok + self.stats.pushed_error},
                    )
                    break
        return self.stats

    def _processor(self) -> Any:
        """Resolve the preset's dataset-item processor, if any."""
        if not self.config.processor_name:
            return None
        from actor_factory.processors import PROCESSORS

        return PROCESSORS.get(self.config.processor_name)
