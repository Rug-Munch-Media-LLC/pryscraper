"""— Apify Actor Factory: data-source transparency sections.

Renders the "Data source" section for API-backed Actors, mapping known
data-source name substrings to source descriptions, URL patterns and docs.

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec

_DATA_SOURCES: dict[str, tuple[str, str, str]] = {
    # name-substring: (source name, example URL pattern, docs URL)
    "app-store": (
        "Apple iTunes Search/Lookup API + customer-reviews RSS",
        "https://itunes.apple.com/lookup?id=<APP_ID>&country=us",
        "https://performance-partners.apple.com/search-api",
    ),
    "github-release": (
        "GitHub public REST API (releases endpoint)",
        "https://api.github.com/repos/<OWNER>/<REPO>/releases",
        "https://docs.github.com/rest/releases/releases",
    ),
    "npm-package": (
        "npm registry + downloads count APIs",
        "https://registry.npmjs.org/<PACKAGE> | https://api.npmjs.org/downloads/point/last-month/<PACKAGE>",
        "https://github.com/npm/registry/blob/main/docs/RESOURCES.md",
    ),
    "pypi-package": (
        "PyPI JSON API",
        "https://pypi.org/pypi/<PACKAGE>/json",
        "https://warehouse.pypa.io/api-reference/json.html",
    ),
    "hacker-news": (
        "Hacker News Algolia public search API",
        "https://hn.algolia.com/api/v1/search?query=<KEYWORD>&tags=story",
        "https://hn.algolia.com/api",
    ),
    "rdap": (
        "RDAP bootstrap protocol (registration data access)",
        "https://rdap.org/domain/<DOMAIN>",
        "https://about.rdap.org",
    ),
    "arxiv": (
        "arXiv public API",
        "http://export.arxiv.org/api/query?search_query=all:<TERM>",
        "https://info.arxiv.org/help/api",
    ),
    "podcast-review": (
        "Apple Podcasts customer-review RSS feeds",
        "https://itunes.apple.com/us/rss/customerreviews/id=<PODCAST_ID>/json",
        "https://performance-partners.apple.com/search-api",
    ),
    "fx-rate": (
        "open Exchange Rates API (free tier, no key)",
        "https://open.er-api.com/v6/latest/USD",
        "https://www.exchangerate-api.com/docs/free",
    ),
    "crypto-market": (
        "CoinGecko public market API (free tier)",
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd",
        "https://docs.coingecko.com/reference/introduction",
    ),
}


def _data_source_section(spec: ActorSpec) -> str:
    """Transparency block for API-backed Actors: exactly where the data
    comes from. Trust signal + long-tail SEO keywords in one section."""
    name = spec.name.lower()
    if spec.processor != "jsondata":
        return ""
    for needle, (source, pattern, docs) in _DATA_SOURCES.items():
        if needle in name:
            return (
                "## Data source\n\n"
                f"This Actor reads **{source}** - a documented public API. "
                "No scraping fragility, no anti-bot lottery: the data you "
                "get is the data the source publishes.\n\n"
                "**URL pattern** (paste your own targets):\n\n"
                f"```\n{pattern}\n```\n\n"
                f"API reference: {docs}\n\n"
            )
    return (
        "## Data source\n\n"
        "This Actor reads documented public JSON APIs. Paste any endpoint "
        "returning JSON as a target URL - responses are parsed into clean "
        "dataset records with honest skip-reporting for non-JSON replies.\n\n"
    )
