"""Dataset push with bounded exponential backoff."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pry.actors.apify_actor.models import ApifyActorOutput

logger = logging.getLogger(__name__)

MAX_PUSH_RETRIES = 3
MAX_PUSH_BACKOFF_SECONDS = 10


async def _push_with_retry(
    actor: Any,
    data: ApifyActorOutput,
    max_retries: int = MAX_PUSH_RETRIES,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Push data to the Apify dataset with exponential backoff retry.

    T1 win #22: Don't lose data on transient network errors. Exhausting the
    retries logs a diagnostic; the caller keeps scraping the remaining URLs.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            await actor.push_data(data.to_dataset_item())
            return
        except (OSError, RuntimeError, TimeoutError) as e:
            last_error = e
            wait = min(2**attempt, MAX_PUSH_BACKOFF_SECONDS)
            logger.warning(
                "apify_push_retry",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "wait": wait,
                    "error": str(e),
                },
            )
            if attempt < max_retries - 1:
                await sleep(wait)
    logger.error("apify_push_failed", extra={"error": str(last_error)})
