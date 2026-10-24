"""Pry — X (Twitter) page parser facade.

One entry point over the two parsing layers:

1. :func:`datasets.attention.x_ssr.extract_tweet_results` — the SSR JSON
   payload X embeds in the page (authoritative: counts, timestamps, media).
2. :func:`datasets.attention.x_dom.parse_dom` — the rendered tweet blocks
   (ids, handles, text, timestamps only).

Contract:
    >>> posts, source = parse_posts(html)
    >>> posts[0]["author"]["handle"], source
    ('jack', 'ssr')

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.attention.x_dom import parse_dom
from datasets.attention.x_fields import post_from_result
from datasets.attention.x_ssr import extract_tweet_results

__all__ = ["parse_posts"]


def parse_posts(html: str) -> tuple[list[dict[str, Any]], str]:
    """Parse a page into normalized posts plus the layer used (``ssr``/``dom``/``none``)."""
    posts = [post for post in map(post_from_result, extract_tweet_results(html)) if post]
    if posts:
        return posts, "ssr"
    dom_posts = parse_dom(html)
    return (dom_posts, "dom") if dom_posts else ([], "none")
