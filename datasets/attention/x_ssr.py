"""Pry — X (Twitter) SSR JSON extraction.

X embeds its GraphQL timeline payload inside a page ``<script>`` as a JS
expression whose nested JSON strings are backslash-escaped (``\\"``). This
module unescapes the bodies, finds the smallest enclosing JSON object for
every ``"tweet_results"`` key, and returns the tweet nodes in document
order without duplicates.

Contract:
    >>> nodes = extract_tweet_results(html)
    >>> nodes[0]["rest_id"], bool(nodes[0]["result"])
    ('20', True)

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import re
from typing import Any

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_TWEET_KEY_RE = re.compile(r'"tweet_results"')
_DECODER = json.JSONDecoder()

MAX_BACKTRACK = 800
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r"}

__all__ = ["MAX_BACKTRACK", "extract_tweet_results", "unescape_js"]


def unescape_js(text: str) -> str:
    """Decode the JS string escapes X wraps its embedded JSON in."""
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length:
            decoded = _ESCAPES.get(text[index + 1])
            if decoded is not None:
                out.append(decoded)
                index += 2
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _walk_tweet_results(node: Any, found: list[dict[str, Any]]) -> None:
    """Collect every ``tweet_results`` value nested in ``node``."""
    if isinstance(node, dict):
        value = node.get("tweet_results")
        if isinstance(value, dict):
            found.append(value)
        for child in node.values():
            _walk_tweet_results(child, found)
    elif isinstance(node, list):
        for child in node:
            _walk_tweet_results(child, found)


def _decode_enclosing(text: str, index: int) -> dict[str, Any] | None:
    """Return the closest parseable JSON object enclosing ``index``."""
    for back in range(1, MAX_BACKTRACK):
        start = index - back
        if start < 0:
            return None
        if text[start] != "{":
            continue
        try:
            obj, _ = _DECODER.raw_decode(text, start)
        except ValueError:
            continue
        return obj if isinstance(obj, dict) else None
    return None


def extract_tweet_results(html: str) -> list[dict[str, Any]]:
    """Ordered, de-duplicated ``tweet_results`` nodes from the page scripts."""
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for body in _SCRIPT_RE.findall(html):
        if "tweet_results" not in body:
            continue
        text = unescape_js(body)
        for match in _TWEET_KEY_RE.finditer(text):
            obj = _decode_enclosing(text, match.start())
            if obj is None:
                continue
            found: list[dict[str, Any]] = []
            _walk_tweet_results(obj, found)
            for entry in found:
                tweet_id = str(entry.get("rest_id") or "")
                if tweet_id and tweet_id not in seen:
                    seen.add(tweet_id)
                    ordered.append(entry)
    return ordered
