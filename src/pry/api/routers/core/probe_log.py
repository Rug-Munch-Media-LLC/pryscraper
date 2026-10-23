# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""One-line, transition-aware reporting for dependency probes.

Incident 2026-10-23: ``/health`` reported ``ollama: false`` on every call
because ``PRY_OLLAMA_URL`` was unset and the default ``localhost:11434`` has
nothing listening inside the container.  Each probe logged
``health_exception_handler`` at WARNING **with a full traceback** — 61
tracebacks / 10 min, 261 KB of 326 KB total log output (80%).  The traceback
was always the same three frames (``client.get`` -> transport -> ConnectError),
so it carried no information a single line does not: a dead *optional*
dependency is expected behaviour, and under load a probe that hits its budget
is expected too.

:class:`ProbeLog` remembers the last observed state per dependency:

* transition to down   -> ONE line (info for optional, warning for critical)
* still down           -> debug (silent in production)
* transition to up     -> ONE "recovered" line

Steady state is therefore silent: the log rate no longer depends on the probe
interval, only on real state changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeTiming:
    """How long one probe took, and the budget it was given."""

    elapsed_ms: int
    budget_ms: int


@dataclass(frozen=True)
class ProbeFailure:
    """Why a probe failed, and whether its dependency is optional."""

    reason: str
    error_type: str | None = None
    optional: bool = False


class ProbeLog:
    """Per-dependency state memory that collapses repeat failures to one line."""

    def __init__(self) -> None:
        self._last: dict[str, bool] = {}

    def report(
        self,
        dependency: str,
        ok: bool,
        timing: ProbeTiming,
        failure: ProbeFailure | None = None,
    ) -> None:
        """Record one probe outcome and log at most one line for it."""
        previous = self._last.get(dependency)
        self._last[dependency] = ok
        failure = failure or ProbeFailure(reason="unhealthy")
        extra: dict[str, Any] = {
            "dependency": dependency,
            "optional": failure.optional,
            "elapsed_ms": timing.elapsed_ms,
            "budget_ms": timing.budget_ms,
        }
        if ok:
            if previous is False:
                logger.info("health_probe_recovered", extra=extra)
            return
        extra["reason"] = failure.reason
        extra["error_type"] = failure.error_type
        if previous is False:
            logger.debug("health_probe_still_down", extra=extra)
        elif failure.optional:
            logger.info("health_probe_failed", extra=extra)
        else:
            logger.warning("health_probe_failed", extra=extra)

    def reset(self) -> None:
        """Forget observed state (tests, and after a config reload)."""
        self._last.clear()


#: Process-wide probe reporter.
probes = ProbeLog()

__all__ = ["ProbeFailure", "ProbeLog", "ProbeTiming", "probes"]
