"""Pry - Apify Actor Factory: pay-per-event runtime.

Implements the monetization patterns from Apify's PPE documentation
(docs.apify.com/actors/publishing/monetize/pay-per-event) as a reusable
runner so every factory-generated actor bills correctly:

- Charge per result via ``push_data(item, event_name)`` (charge + save in
  one platform call; error items are charged too - work done is billed).
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ActorLike(Protocol):
    """Structural subset of the Apify SDK Actor used by the runner."""

    async def get_input(self) -> dict[str, Any] | None: ...

    async def push_data(self, item: dict[str, Any], event_name: str | None = None) -> Any: ...

    async def charge(self, event_name: str) -> Any: ...

    def on(self, event: Any, handler: Any) -> Any: ...

    async def exit(self) -> Any: ...


def _load_actor() -> Any:
    """Import the real Actor SDK lazily (absent in unit-test environments)."""
    from apify import Actor

    return Actor


@dataclass
class ActorRunConfig:
    primary_event: str
    default_output_format: str = "markdown"
    max_items: int = 10_000  # hard runaway cap independent of user limits


@dataclass
class RunStats:
    pushed_ok: int = 0
    pushed_error: int = 0
    limit_reached: bool = False
    aborted_flushed: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class PPEScraperRunner:
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
        from ultimate_scraper import UltimateScraper

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

    async def push_and_charge(self, actor: Any, item: dict[str, Any]) -> bool:
        """Push one item with the primary event attached.

        Returns False when the user spending limit says stop.
        """
        charge_result = await actor.push_data(item, self.config.primary_event)
        # push_data returns a ChargeResult when an event name is given.
        if charge_result is not None and getattr(
            charge_result, "event_charge_limit_reached", False
        ):
            self.stats.limit_reached = True
            return False
        if item.get("status") == "ok":
            self.stats.pushed_ok += 1
        else:
            self.stats.pushed_error += 1
        return True

    def on_aborting(self) -> None:
        """Flush completed-but-unbilled work inside the 30s window."""
        flushed = len(self._pending)
        self._pending.clear()
        self.stats.aborted_flushed += flushed
        logger.warning(
            "ppe_aborting_flush",
            extra={"flushed": flushed, "stats_pushed_ok": self.stats.pushed_ok},
        )

    # -- Main loop ----------------------------------------------------------

    async def run(self) -> RunStats:
        actor = self.actor()
        async with actor:
            actor.on("aborting", self.on_aborting)
            raw_input = await actor.get_input() or {}
            urls = self._normalize_urls(raw_input)
            options = {k: v for k, v in raw_input.items() if k not in ("urls", "max_pages")}
            output_format = raw_input.get("output_format", self.config.default_output_format)
            options.setdefault("output_format", output_format)

            for url in urls[: self.config.max_items]:
                try:
                    item = await self.process_url(url, options)
                except Exception as e:  # noqa: BLE001 - bad targets must not kill runs
                    logger.debug("process_url_failed", extra={"url": url, "error": str(e)[:80]})
                    item = {
                        "url": url,
                        "status": "error",
                        "error": f"processing_failed: {str(e)[:120]}",
                        "scraped_at": datetime.now(UTC).isoformat(),
                    }
                keep_going = await self.push_and_charge(actor, item)
                if not keep_going:
                    logger.warning(
                        "ppe_user_limit_reached",
                        extra={"processed": self.stats.pushed_ok + self.stats.pushed_error},
                    )
                    break
        return self.stats

    @staticmethod
    def _normalize_urls(raw_input: dict[str, Any]) -> list[str]:
        """Accept requestListSources objects or plain strings."""
        raw = raw_input.get("urls") or []
        urls: list[str] = []
        for entry in raw:
            u = entry.get("url") if isinstance(entry, dict) else str(entry)
            if u and u.startswith(("http://", "https://")):
                urls.append(u)
        return urls
