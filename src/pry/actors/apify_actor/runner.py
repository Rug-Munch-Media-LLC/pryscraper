"""Pry Apify Actor entry point."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry.actors.apify_actor.input_stage import prepare_run
from pry.actors.apify_actor.loop import run_loop
from pry.engine.ultimate_scraper import UltimateScraper

if TYPE_CHECKING:
    from collections.abc import Callable


def _load_actor() -> Any:
    """Import the Apify SDK lazily so this package imports without it installed."""
    from apify import Actor

    return Actor


async def main(actor: Any | None = None, scraper_factory: Callable[[], Any] | None = None) -> None:
    """Pry Apify Actor entry point (both dependencies are injectable for tests)."""
    actor = _load_actor() if actor is None else actor
    scraper_factory = UltimateScraper if scraper_factory is None else scraper_factory

    async with actor:
        run = await prepare_run(actor, scraper_factory)
        if run is None:
            return
        await run_loop(run)
