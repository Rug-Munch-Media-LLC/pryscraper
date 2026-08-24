# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Abuse protection for pay-per-event Actor runs.

Billing is tied to outcomes, so a hostile input set (hundreds of URLs that
all fail) burns run time, pollutes success metrics and invites refund
storms - even though error items are charged. The AbuseGuard watches the
failure pattern while items stream through and:

1. **Trips** after ``consecutive_limit`` consecutive failures with no
   success, or when the failure rate over the first ``rate_sample`` items
   crosses ``rate_threshold``.
2. **Throttles** on trip: inter-item delay escalates exponentially so a
   sabotaging client stops getting cheap throughput.
3. **Emits a honeypot record** into the dataset - a structured fingerprint
   of the run (run id, user id when resolvable, failure stats, URL hashes)
   for cross-run abuse auditing.
4. **Aborts gracefully** if the grace window passes with no success: a
   clean "input rejected" beats churning 500 doomed requests.

Processor-aware: for monitoring Actors an unchanged/skipped page is a
*normal* outcome, not a failure - only hard errors count there.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CONSECUTIVE_LIMIT_DEFAULT = 12
RATE_SAMPLE_DEFAULT = 15
RATE_THRESHOLD_DEFAULT = 0.9
GRACE_WINDOW_DEFAULT = 5
BASE_DELAY_DEFAULT = 0.5
MAX_DELAY_DEFAULT = 30.0


@dataclass
class AbuseGuard:
    """Circuit breaker + throttle + honeypot telemetry for one run."""

    consecutive_limit: int = CONSECUTIVE_LIMIT_DEFAULT
    rate_sample: int = RATE_SAMPLE_DEFAULT
    rate_threshold: float = RATE_THRESHOLD_DEFAULT
    grace_window: int = GRACE_WINDOW_DEFAULT
    base_delay: float = BASE_DELAY_DEFAULT
    max_delay: float = MAX_DELAY_DEFAULT
    skip_counts_as_failure: bool = True

    # live state
    consecutive_failures: int = 0
    total_failures: int = 0
    total_seen: int = 0
    _tripped: bool = False
    _trip_reason: str = ""
    _grace_remaining: int = field(default=-1)
    _delay: float = 0.0
    _recent_url_hashes: list[str] = field(default_factory=list)

    # -- recording -----------------------------------------------------------

    def record(self, status: str, url: str = "") -> None:
        """Feed one processed item's outcome into the guard."""
        self.total_seen += 1
        if url:
            self._recent_url_hashes.append(hashlib.sha256(url.encode()).hexdigest()[:12])
            self._recent_url_hashes = self._recent_url_hashes[-25:]

        failed = status == "error" or (status == "skipped" and self.skip_counts_as_failure)
        if not failed:
            self.consecutive_failures = 0
            if self._tripped:
                # recovery inside the grace window - stand the throttle down
                self._grace_remaining = -1
                self._delay = 0.0
                logger.info("abuse_guard_recovered", extra={"total_seen": self.total_seen})
        else:
            self.total_failures += 1
            self.consecutive_failures += 1
            if not self._tripped and self.consecutive_failures >= self.consecutive_limit:
                self._trip(f"consecutive_failures={self.consecutive_failures}")
            elif self._tripped and self._grace_remaining > 0:
                self._grace_remaining -= 1

        # Rate tripwire checks cumulative stats regardless of this item's
        # outcome - a single late success must not mask a hostile input set.
        if (
            not self._tripped
            and self.total_seen >= self.rate_sample
            and self.total_failures / self.total_seen >= self.rate_threshold
        ):
            pct = round(100 * self.total_failures / self.total_seen)
            self._trip(f"failure_rate={pct}% over {self.total_seen}")

    def _trip(self, reason: str) -> None:
        self._tripped = True
        self._trip_reason = reason
        self._grace_remaining = self.grace_window
        self._delay = self.base_delay
        logger.warning("abuse_guard_tripped", extra={"reason": reason})

    # -- state queries ---------------------------------------------------------

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def trip_reason(self) -> str:
        return self._trip_reason

    @property
    def delay(self) -> float:
        """Current throttle delay in seconds (0 when not tripped)."""
        return self._delay

    def escalate_throttle(self) -> float:
        """Double the throttle after each throttled request; returns delay."""
        if self._tripped:
            self._delay = min(self._delay * 2 or self.base_delay * 2, self.max_delay)
        return self._delay

    @property
    def should_abort(self) -> bool:
        """True when tripped AND the grace window expired without success."""
        return self._tripped and self._grace_remaining == 0

    # -- honeypot telemetry ------------------------------------------------------

    def honeypot_record(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Structured abuse fingerprint for the dataset / audit trail."""
        record: dict[str, Any] = {
            "honeypot": True,
            "status": "rejected",
            "trigger": self._trip_reason,
            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "stats": {
                "total_seen": self.total_seen,
                "total_failures": self.total_failures,
                "consecutive_failures": self.consecutive_failures,
                "failure_rate": round(self.total_failures / self.total_seen, 3)
                if self.total_seen
                else 0.0,
            },
            "url_hashes": list(self._recent_url_hashes),
            "run_id": os.environ.get("APIFY_RUN_ID", ""),
            "actor_id": os.environ.get("APIFY_ACTOR_ID", ""),
            "user_id": os.environ.get("APIFY_USER_ID", ""),
        }
        if extra:
            record.update(extra)
        return record
