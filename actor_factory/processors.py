"""Pry - Apify Actor Factory: per-actor item processors.

Each niche actor must DO what its store description promises - not just
run a generic scrape. Processors take Pry's raw scrape result plus input
options and return the enriched dataset item.

Every processor is pure (HTML/text in -> dict out) so tests need no network.

This module is a thin re-export facade; implementations live in the
focused sibling modules (processors_common, processors_corpus,
processors_html, processors_json, processors_invoice, processors_registry).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from actor_factory.processors_common import (  # noqa: F401
    ProcessorFn,
    _base_item,
    _raw_html,
    _simhash64,
)
from actor_factory.processors_corpus import (
    process_corpus,
    process_monitor,
)
from actor_factory.processors_html import (
    process_audit,
    process_backlinks,
    process_leads,
    process_news,
    process_seo,
    process_tech,
)
from actor_factory.processors_invoice import process_invoice
from actor_factory.processors_json import (
    process_extract,
    process_jsondata,
    process_price,
)
from actor_factory.processors_registry import (
    PROCESSORS,
    get_processor,
)

__all__ = [
    "PROCESSORS",
    "ProcessorFn",
    "get_processor",
    "process_audit",
    "process_backlinks",
    "process_corpus",
    "process_extract",
    "process_invoice",
    "process_jsondata",
    "process_leads",
    "process_monitor",
    "process_news",
    "process_price",
    "process_seo",
    "process_tech",
]
