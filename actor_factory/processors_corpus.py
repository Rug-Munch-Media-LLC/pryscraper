"""Pry - Apify Actor Factory: corpus + change-monitor processors.

Simhash-based content processors: boilerplate/near-duplicate filtering for
clean corpora, and diff-by-simhash change detection against prior runs.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from actor_factory.processors_common import _base_item, _simhash64


def process_corpus(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Filter boilerplate shells and near-duplicates for clean corpora."""
    item = _base_item(url, result)
    content = item["content"] or ""
    min_chars = int(options.get("min_content_chars", 500) or 0)
    if item["status"] == "ok" and len(content) < min_chars:
        item["status"] = "skipped"
        item["error"] = f"content shorter than {min_chars} chars"
        item.pop("content", None)
        return item
    if options.get("dedupe", True) and item["status"] == "ok":
        fingerprint = _simhash64(content)
        if fingerprint and fingerprint in state.setdefault("seen_hashes", set()):
            item["status"] = "skipped"
            item["error"] = "near-duplicate of an earlier document"
            item.pop("content", None)
            return item
        if fingerprint:
            state["seen_hashes"].add(fingerprint)
    return item


def process_monitor(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Baseline + change detection: stable hash of visible content; emits
    `changed` only when the fingerprint differs from the previous run."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    content = item["content"] or ""
    threshold = int(options.get("change_threshold", 3) or 3)
    fingerprint = _simhash64(content)
    seen: dict[str, int] = state.setdefault("fingerprints", {})
    previous = seen.get(url)
    changed: bool | None
    if previous is None:
        changed = None  # baseline run - nothing to compare yet
        detail = "baseline captured"
    elif previous == fingerprint:
        changed = False
        detail = "unchanged since previous capture"
    else:
        distance = bin(previous ^ fingerprint).count("1")
        changed = distance > threshold
        detail = f"simhash distance {distance} (threshold {threshold})"
    seen[url] = fingerprint
    include_unchanged = bool(options.get("include_unchanged", False))
    if changed is False and not include_unchanged:
        item["status"] = "skipped"
        item["error"] = "unchanged"
        item.pop("content", None)
    item.pop("content", None)
    item["monitor"] = {
        "fingerprint": str(fingerprint),
        "changed": changed,
        "detail": detail,
    }
    return item
