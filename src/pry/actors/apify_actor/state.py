"""Mutable state of one actor run."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.actors.apify_actor.models import ApifyActorInput


@dataclass
class ActorRun:
    """Everything the crawl loop needs, passed as one argument."""

    actor: Any
    scraper: Any
    validated: ApifyActorInput
    base_options: dict[str, Any]
    to_visit: list[str] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)
    total_scraped: int = 0
    total_errors: int = 0
