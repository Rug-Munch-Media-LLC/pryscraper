"""Canonical ``Retry-After`` handling for the scraper fleet.

One job: decide how long to wait before the next attempt. When the server told
us (``Retry-After``), that answer wins over our own exponential table — sleeping
less than the server asked is how a fleet gets its IP space banned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

#: A server asking for more than this is either broken or hostile; we cap and
#: let the caller's tier/breaker policy decide to abandon the target.
RETRY_AFTER_CAP_S = 30.0


def retry_delay(
    attempt: int,
    base: float,
    *,
    header: str | None = None,
    cap: float = RETRY_AFTER_CAP_S,
    now: datetime | None = None,
) -> float:
    """Seconds to sleep before attempt ``attempt + 1``.

    ``Retry-After`` (delta-seconds or HTTP-date) is honoured and capped at
    ``cap``; absent or unparseable header falls back to ``base * 2**attempt``,
    also capped. Never negative.
    """
    if header:
        raw = header.strip()
        seconds: float | None = None
        try:
            seconds = float(raw)
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                when = None
            if when is not None:
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                seconds = (when - (now or datetime.now(UTC))).total_seconds()
        if seconds is not None:
            return min(max(seconds, 0.0), cap)
    return min(base * (2**attempt), cap)


__all__ = ["RETRY_AFTER_CAP_S", "retry_delay"]
