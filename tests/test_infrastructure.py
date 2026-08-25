# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for production infrastructure (db, observability)."""

from pry.core.db import _has_sqlalchemy, get_db
from pry.core.observability import track_llm_call, track_request, track_scrape


def test_observability_track_request() -> None:
    with track_request("/test"):
        pass  # Should not raise


def test_observability_track_scrape() -> None:
    with track_scrape("direct"):
        pass


def test_observability_track_llm() -> None:
    track_llm_call("openai", "gpt-4o-mini", 0.001)


def test_db_is_available() -> None:
    # Just check it doesn't crash; may be unavailable if no sqlalchemy
    db = get_db()
    if _has_sqlalchemy:
        assert db is not None
