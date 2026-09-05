"""Pry — shared clock helpers (monkeypatchable for tests).

Single hook for "current UTC time" plus ISO round-tripping so tests can
freeze time by patching :func:`now` in one place.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """Current UTC timestamp (single hook so tests can freeze time)."""
    return datetime.now(UTC)


def utc_iso(dt: datetime) -> str:
    """ISO-8601 with explicit UTC offset (round-trips via fromisoformat)."""
    return dt.isoformat()


def parse_iso(value: str) -> datetime:
    """Parse a stored ISO timestamp back into an aware datetime."""
    return datetime.fromisoformat(value)
