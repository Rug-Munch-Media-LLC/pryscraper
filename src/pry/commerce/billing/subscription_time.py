"""Pry — subscription time helpers.

Small, pure datetime utilities shared by the subscription billing modules:
ISO-8601 round-tripping (``_utc_iso`` / ``_parse_iso``) and calendar-month
arithmetic with day-of-month clamping (``_add_months``).

The live clock hook (``_now``) lives in :mod:`pry.commerce.billing.subscription`
so tests can freeze time by monkeypatching the facade module.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import calendar
from datetime import datetime


def _utc_iso(dt: datetime) -> str:
    """ISO-8601 with explicit UTC offset (round-trips via fromisoformat)."""
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse a stored ISO timestamp back into an aware datetime."""
    return datetime.fromisoformat(value)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months to *dt*, clamping the day-of-month."""
    month_index = dt.year * 12 + (dt.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
