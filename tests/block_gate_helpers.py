# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Deterministic body builders for the block-detection size gates.

Pure: builds synthetic HTML of a requested size, no network and no clock.
Shared by tests/test_block_detection_gates.py so the fixture bytes live in
exactly one place.
"""

from __future__ import annotations

#: Deterministic filler for building realistically-sized bodies. Real article
#: text is long prose, so padding with words (not one repeated character) keeps
#: the synthetic page honest about what a large body actually looks like.
_FILLER = (
    "The court filings describe a dispute over digital assets and the "
    "arbitration panel has yet to publish its ruling. "
)


def _large_body(phrase: str, target_bytes: int) -> str:
    """Return an article-sized body that contains ``phrase`` exactly once.

    The phrase is placed mid-body so it cannot be mistaken for a block page
    that happens to be short. Caller asserts on the resulting size.
    """
    head = "<html><body><article><p>"
    tail = "</p></article></body></html>"
    body = _FILLER * (target_bytes // len(_FILLER) + 1)
    marker_at = len(body) // 2
    return head + body[:marker_at] + phrase + body[marker_at:] + tail
