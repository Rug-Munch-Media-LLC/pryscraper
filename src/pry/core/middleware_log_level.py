# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""INFO-vs-DEBUG level policy for HTTP request logging.

Probe and metrics endpoints are polled every few seconds; logging them at INFO
made up 28% of all log lines (130/460 in a 10-minute sample, 2026-10-23).
Split out of ``middleware_http`` so that module stays shrink-only.
"""

from __future__ import annotations

import logging

PROBE_PATHS = frozenset({"/health", "/healthz", "/live", "/ready", "/version", "/metrics"})


def level_for(path: str) -> int:
    """INFO for real traffic, DEBUG for orchestrator/prometheus probes."""
    return logging.DEBUG if path in PROBE_PATHS else logging.INFO


__all__ = ["PROBE_PATHS", "level_for"]
