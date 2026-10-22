# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Prometheus metric objects for Pry.

Split out of ``pry.core.observability`` so the collector helpers and the
tracing helpers can each import the metric objects without a cycle.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

_has_prometheus = True

REQUEST_COUNT = Counter("pry_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("pry_request_duration_seconds", "Request latency", ["endpoint"])
ERROR_COUNT = Counter("pry_request_errors_total", "Request errors", ["method", "endpoint"])
SCRAPE_COUNT = Counter("pry_scrapes_total", "Total scrapes", ["method", "status"])
SCRAPE_FAILURES = Counter(
    "pry_scrape_failures_total", "Scrape failures by reason", ["method", "reason"]
)
SCRAPE_LATENCY = Histogram("pry_scrape_duration_seconds", "Scrape latency", ["method"])
LLM_CALLS = Counter("pry_llm_calls_total", "Total LLM calls", ["provider", "model"])
LLM_COST = Counter("pry_llm_cost_usd_total", "Total LLM cost in USD", ["provider"])
TEMPLATE_USAGE = Counter("pry_template_usage_total", "Template usage", ["template_id"])
CACHE_HITS = Counter("pry_cache_hits_total", "Cache hits", ["cache_type"])
ACTIVE_CONNECTIONS = Gauge("pry_active_connections", "Active connections", ["type"])
ACTIVE_SESSIONS = Gauge(
    "pry_active_sessions",
    "Active scraping/browser sessions (bounded by PRY_MAX_SESSIONS)",
    ["type"],
)
