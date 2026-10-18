# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Metric-tracking helpers (request, scrape, session, LLM, template).

Split out of ``pry.core.observability`` (which re-exports these names).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pry.core.metrics_defs import (
    ACTIVE_SESSIONS,
    ERROR_COUNT,
    LLM_CALLS,
    LLM_COST,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    SCRAPE_COUNT,
    SCRAPE_LATENCY,
    TEMPLATE_USAGE,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def track_request(endpoint: str, method: str = "GET") -> Iterator[None]:
    """Context manager to track request metrics and timing.

    Increments ``pry_requests_total`` (with status) and observes
    ``pry_request_duration_seconds``. When the wrapped code raises, also
    increments ``pry_request_errors_total`` for the endpoint.
    """
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.time() - start
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
        if status == "error":
            ERROR_COUNT.labels(method=method, endpoint=endpoint).inc()


@contextmanager
def track_scrape(method: str = "direct") -> Iterator[None]:
    """Context manager to track scrape metrics."""
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        SCRAPE_COUNT.labels(method=method, status=status).inc()
        SCRAPE_LATENCY.labels(method=method).observe(time.time() - start)


def session_started(session_type: str = "browser") -> None:
    """Record that a scraping/browser session started (active gauge += 1)."""
    ACTIVE_SESSIONS.labels(type=session_type).inc()


def session_ended(session_type: str = "browser") -> None:
    """Record that a scraping/browser session ended (active gauge -= 1)."""
    ACTIVE_SESSIONS.labels(type=session_type).dec()


def track_llm_call(provider: str, model: str, cost: float = 0.0) -> None:
    LLM_CALLS.labels(provider=provider, model=model).inc()
    if cost > 0:
        LLM_COST.labels(provider=provider).inc(cost)


def track_template(template_id: str) -> None:
    TEMPLATE_USAGE.labels(template_id=template_id).inc()
