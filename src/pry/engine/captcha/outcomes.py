"""Pry — typed CAPTCHA outcomes.

One vocabulary for the whole ladder: every rung reports a status, a duration
and a reason, and the ladder returns one of the four terminal refusals. Empty
success is not representable.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from dataclasses import dataclass

SOLVED = "solved"
UNSOLVED = "unsolved"
SKIPPED = "skipped"
TIMEOUT = "timeout"
NOT_APPLICABLE = "not_applicable"
FAILED = "failed"

BLOCKED_UNSOLVED = "blocked.captcha_unsolved"
BLOCKED_ROBOTS = "blocked.robots"
SKIPPED_PAID_API = "skipped.paid_api"
UNAVAILABLE_MODEL = "unavailable.model"
UNAVAILABLE_BROWSER = "unavailable.browser"
DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class TierOutcome:
    """One rung of the ladder, as rendered in the attempts trail."""

    tier: str
    status: str
    ms: int
    reason: str = ""
    token: str | None = None
    html: str | None = None

    def line(self) -> str:
        """Render as ``tier · outcome · ms · reason`` for diagnostics."""
        return f"{self.tier} {self.status} {self.ms}ms {self.reason}".rstrip()
