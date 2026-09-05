"""Pry - Apify Actor Factory: shared processor helpers.

Common building blocks used by every per-actor item processor: the base
dataset-item shape, raw-HTML access, and the simhash fingerprint used by
the corpus and monitor processors.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

ProcessorFn = Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]


def _base_item(url: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "status": result.get("status", "error"),
        "method": result.get("method", "unknown"),
        "scraped_at": result.get("scraped_at"),
        "content": result.get("content", ""),
        "error": result.get("error", ""),
    }


def _raw_html(result: dict[str, Any]) -> str:
    return result.get("raw_html") or ""


def _simhash64(text: str) -> int:
    import hashlib

    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0
    vector = [0] * 64
    for token in tokens:
        h = int(hashlib.md5(token.encode(), usedforsecurity=False).hexdigest(), 16)
        for i in range(64):
            vector[i] += 1 if h & (1 << i) else -1
    return sum(1 << i for i in range(64) if vector[i] > 0)
