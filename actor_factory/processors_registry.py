"""Pry - Apify Actor Factory: processor registry.

Maps actor processor type names to their data transformation functions.
Every processor is pure (HTML/text in -> dict out) so tests need no network.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

from actor_factory.processors_corpus import process_corpus, process_monitor
from actor_factory.processors_html import (
    process_audit,
    process_backlinks,
    process_leads,
    process_news,
    process_seo,
    process_tech,
)
from actor_factory.processors_invoice import process_invoice
from actor_factory.processors_json import process_extract, process_jsondata, process_price
from actor_factory.processors_serp import process_serp
from actor_factory.processors_web import (
    process_crawl,
    process_pdfdoc,
    process_sanctions,
    process_screenshot,
    process_sslcert,
    process_tokensafety,
)

if TYPE_CHECKING:
    from actor_factory.processors_common import ProcessorFn

PROCESSORS: dict[str, ProcessorFn] = {
    "corpus": process_corpus,
    "backlinks": process_backlinks,
    "seo": process_seo,
    "leads": process_leads,
    "news": process_news,
    "price": process_price,
    "tech": process_tech,
    "jsondata": process_jsondata,
    "invoice": process_invoice,
    "audit": process_audit,
    "monitor": process_monitor,
    "extract": process_extract,
    "serp": process_serp,
    "screenshot": process_screenshot,
    "crawl": process_crawl,
    "pdfdoc": process_pdfdoc,
    "sslcert": process_sslcert,
    "tokensafety": process_tokensafety,
    "sanctions": process_sanctions,
}


def get_processor(name: str | None) -> ProcessorFn | None:
    return PROCESSORS.get(name or "")
