"""Validate the actor's input before anything is scraped."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from pry.actors.apify_actor.models import ApifyActorInput, ApifyActorOutput
from pry.actors.apify_actor.options import build_base_options
from pry.actors.apify_actor.push import _push_with_retry
from pry.actors.apify_actor.state import ActorRun

if TYPE_CHECKING:
    from collections.abc import Callable


async def _push_invalid_input(actor: Any, error: ValidationError) -> None:
    """Report a malformed run so the caller sees why nothing was scraped."""
    actor.log.error("pry_actor_input_invalid", extra={"error": str(error)})
    await _push_with_retry(
        actor,
        ApifyActorOutput(
            url="",
            status="error",
            error=f"Invalid input: {error}",
            scraped_at=datetime.now(UTC).isoformat(),
        ),
    )


async def prepare_run(actor: Any, scraper_factory: Callable[[], Any]) -> ActorRun | None:
    """Build the run state, or push the input error and return ``None``."""
    raw_input = await actor.get_input() or {}
    try:
        validated = ApifyActorInput.model_validate(raw_input)
    except ValidationError as e:
        await _push_invalid_input(actor, e)
        return None

    configuration = actor.configuration if validated.proxy_config.use_apify_proxies else None
    actor.log.info(
        "pry_actor_start",
        extra={
            "urls": len(validated.urls),
            "max_pages": validated.max_pages,
            "crawl": validated.crawl,
            "timeout": validated.timeout,
        },
    )
    return ActorRun(
        actor=actor,
        scraper=scraper_factory(),
        validated=validated,
        base_options=build_base_options(validated, configuration),
        to_visit=list(validated.urls),
    )
