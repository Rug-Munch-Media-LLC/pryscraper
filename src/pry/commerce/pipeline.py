"""Pry — pipeline hook system for the scraping workflow.
Allows plugins and custom transformations at every stage."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

logger = logging.getLogger(__name__)

# Hook point definitions
HOOK_POINTS = [
    "before_scrape",
    "after_response",
    "before_parse",
    "after_parse",
    "before_extract",
    "after_extract",
    "before_return",
    "on_error",
]

HookFn = Callable[..., Awaitable[dict[str, Any]]]
SyncHookFn = Callable[..., dict[str, Any]]


class Pipeline:
    """Scraping pipeline with pluggable hooks at each stage.

    Usage:
        pipeline = Pipeline()
        pipeline.register("before_scrape", my_async_hook)
        pipeline.register("after_response", my_sync_hook)

        result = await pipeline.run("before_scrape", url=url)
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn | SyncHookFn]] = {p: [] for p in HOOK_POINTS}

    def register(
        self,
        hook_point: str,
        fn: HookFn | SyncHookFn,
        priority: int = 0,
    ) -> None:
        """Register a hook function at a hook point.

        Args:
            hook_point: One of HOOK_POINTS
            fn: Async or sync function that receives **kwargs and returns a dict
            priority: Lower runs first (default 0)
        """
        if hook_point not in self._hooks:
            raise ValueError(f"Unknown hook point: {hook_point}. Valid: {HOOK_POINTS}")
        self._hooks[hook_point].append(fn)
        logger.debug("hook_registered", extra={"point": hook_point, "fn": fn.__name__})

    async def run(self, hook_point: str, **kwargs: Any) -> dict[str, Any]:
        """Run all hooks at a hook point, passing kwargs through the chain.

        Each hook receives the output of the previous hook as input.
        Returns the final merged context.
        """
        context = dict(kwargs)
        for fn in self._hooks.get(hook_point, []):
            try:
                if _is_async(fn):
                    result = await cast("HookFn", fn)(**context)
                else:
                    result = cast("SyncHookFn", fn)(**context)
                if isinstance(result, dict):
                    context.update(result)
            except Exception as e:
                logger.exception(
                    "hook_failed",
                    extra={"point": hook_point, "fn": getattr(fn, "__name__", str(fn))},
                )
                if hook_point == "on_error":
                    context["error"] = str(e)
                else:
                    context.setdefault("errors", []).append(str(e))
        return context

    def clear(self, hook_point: str | None = None) -> None:
        """Clear hooks at a point, or all hooks if point is None."""
        if hook_point:
            self._hooks[hook_point] = []
        else:
            for p in HOOK_POINTS:
                self._hooks[p] = []

    def list_hooks(self) -> dict[str, list[str]]:
        """List all registered hooks by hook point."""
        return {
            p: [getattr(fn, "__name__", str(fn)) for fn in fns] for p, fns in self._hooks.items()
        }


def _is_async(fn: Any) -> bool:
    import asyncio
    import inspect

    return asyncio.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn)


# ── Built-in hooks ──


async def log_request(**kwargs: Any) -> dict[str, Any]:
    """Log scraping requests."""
    logger.info(
        "pipeline_scrape",
        extra={"url": kwargs.get("url", ""), "hook": kwargs.get("hook_point", "")},
    )
    return {}


async def strip_html_comments(**kwargs: Any) -> dict[str, Any]:
    """Remove HTML comments from raw content."""
    import re

    html = kwargs.get("html", "")
    if html:
        cleaned = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        return {"html": cleaned}
    return {}


async def extract_all_links(**kwargs: Any) -> dict[str, Any]:
    """Extract all href links from HTML (runs at after_response)."""
    from lxml import html as lxml_html

    html_content = kwargs.get("html", "")
    if not html_content:
        return {}
    try:
        tree = lxml_html.fromstring(html_content)
        links = tree.xpath("//a/@href")
        return {"extracted_links": links}
    except Exception:  # noqa: BLE001
        return {}


# Global pipeline singleton
_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    """Get or create the global pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
        # Register built-in hooks
        _pipeline.register("after_response", extract_all_links, priority=100)
    return _pipeline


async def run_pipeline(hook_point: str, **kwargs: Any) -> dict[str, Any]:
    """Convenience: run a hook point on the global pipeline."""
    return await get_pipeline().run(hook_point, **kwargs)
