"""Input planning and crawl expansion for the actor runner."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from actor_factory.abuse_guard import AbuseGuard
from actor_factory.runner_types import RunPlan
from actor_factory.runner_urls import normalize_urls, same_domain_links

logger = logging.getLogger(__name__)


@dataclass
class CrawlCtx:
    """Mutable crawl state for one URL (depth, visited set, queue, depths)."""

    depth: int
    seen: set[str]
    queue: list[tuple[str, int]]
    depths: dict[str, int]


def _apply_caps(urls: list[str], raw_input: dict[str, Any]) -> tuple[list[str], int | None]:
    max_pages = raw_input.get("max_pages")
    page_cap = max_pages if isinstance(max_pages, int) and max_pages > 0 else None
    if page_cap:
        urls = urls[:page_cap]
    max_items = raw_input.get("max_items")
    if isinstance(max_items, int) and max_items > 0:
        urls = urls[:max_items]
    return urls, page_cap


def _crawl_flags(raw_input: dict[str, Any], processor: str | None) -> tuple[bool, int]:
    raw_depth = raw_input.get("max_depth")
    enabled = processor == "crawl" and isinstance(raw_depth, int) and raw_depth > 0
    return enabled, int(raw_depth) if enabled else 0


class FlowMixin:
    """Normalise input, process one URL, expand same-domain links."""

    def _plan(self, raw_input: dict[str, Any]) -> RunPlan:
        urls, page_cap = _apply_caps(normalize_urls(raw_input), raw_input)
        options = {k: v for k, v in raw_input.items() if k not in ("urls", "max_pages")}
        options.setdefault(
            "output_format",
            raw_input.get("output_format", self.config.default_output_format),
        )
        crawl, max_depth = _crawl_flags(raw_input, self.config.processor_name)
        return RunPlan(
            urls=urls,
            options=options,
            max_depth=max_depth,
            crawl_enabled=crawl,
            page_cap=page_cap,
        )

    async def _handle_trip(self, actor: Any, guard: AbuseGuard) -> bool:
        """Throttle on a soft trip; return True when the run must abort."""
        if not guard.should_abort:
            await asyncio.sleep(guard.delay)
            guard.escalate_throttle()
            return False
        await actor.push_data(guard.honeypot_record())
        logger.error(
            "abuse_guard_abort",
            extra={"reason": guard.trip_reason, "total_seen": guard.total_seen},
        )
        self.stats.pushed_error += 1
        return True

    async def _process(
        self, url: str, options: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            item = await self.process_url(url, options)
            processor = self._processor()
            return processor(url, item, options, state) if processor else item
        except Exception as e:  # noqa: BLE001 - bad targets must not kill runs
            logger.debug("process_url_failed", extra={"url": url, "error": str(e)[:80]})
            return {
                "url": url,
                "status": "error",
                "error": f"processing_failed: {str(e)[:120]}",
                "scraped_at": datetime.now(UTC).isoformat(),
            }

    def _should_expand(self, item: dict[str, Any], ctx: CrawlCtx, plan: RunPlan) -> bool:
        return plan.crawl_enabled and ctx.depth < plan.max_depth and item.get("status") == "ok"

    def _expand(
        self, item: dict[str, Any], url: str, ctx: CrawlCtx, plan: RunPlan
    ) -> None:
        discovered = [
            link
            for link in same_domain_links(item.get("content", ""), url)
            if link not in ctx.seen
            and (plan.page_cap is None or len(ctx.seen) < plan.page_cap)
        ]
        for link in discovered:
            ctx.seen.add(link)
            ctx.depths[link] = ctx.depth + 1
            ctx.queue.append((link, ctx.depth + 1))
        item["discovered_links"] = discovered
