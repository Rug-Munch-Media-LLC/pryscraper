"""Pry — x402 Prometheus metrics.

Dashboard-referenced metrics (grafana/dashboards/x402-payments.json) that were
previously missing from the codebase. All metrics are optional: if
``prometheus_client`` is unavailable the helpers become no-ops so the payment
flow never breaks on observability.

Exposed via the existing ``/metrics`` endpoint (prometheus_client registry).
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram

    _has_prometheus = True
except ImportError:  # pragma: no cover — prometheus-client is a hard dep, guard anyway
    _has_prometheus = False

CHALLENGES_SENT: Any = None
VERIFY_SUCCESS: Any = None
VERIFY_FAILURE: Any = None
SETTLE_TOTAL: Any = None
SETTLE_SUCCESS: Any = None
REPLAY_DETECTED: Any = None
RPC_LATENCY: Any = None
SETTLEMENT_VOLUME_USD: Any = None
FACILITATOR_HEALTH: Any = None
CHAIN_ACTIVE: Any = None
OPERATION_CALLS: Any = None

if _has_prometheus:
    CHALLENGES_SENT = Counter(
        "x402_challenges_sent_total",
        "402 payment challenges (PAYMENT-REQUIRED responses) sent",
        ["operation", "network"],
    )
    VERIFY_SUCCESS = Counter(
        "x402_verify_success_total",
        "Successful payment verifications",
        ["network"],
    )
    VERIFY_FAILURE = Counter(
        "x402_verify_failure_total",
        "Failed payment verifications",
        ["network", "reason"],
    )
    SETTLE_TOTAL = Counter(
        "x402_settle_total",
        "Settlement attempts (all outcomes)",
        ["network"],
    )
    SETTLE_SUCCESS = Counter(
        "x402_settle_success_total",
        "Successful settlements",
        ["network"],
    )
    REPLAY_DETECTED = Counter(
        "x402_replay_detected_total",
        "Replayed tx_hash / payment attempts rejected",
        ["network"],
    )
    RPC_LATENCY = Histogram(
        "x402_rpc_latency_seconds",
        "Blockchain RPC call latency",
        ["network", "method"],
    )
    SETTLEMENT_VOLUME_USD = Counter(
        "x402_settlement_volume_usd_total",
        "Cumulative settled volume in USD",
        ["network", "asset"],
    )
    FACILITATOR_HEALTH = Gauge(
        "x402_facilitator_health",
        "Facilitator health (1 = healthy, 0 = failing)",
        ["facilitator"],
    )
    CHAIN_ACTIVE = Gauge(
        "x402_chain_active",
        "Chain activity (1 = verify/settle attempted, 0 = unsupported)",
        ["network"],
    )
    OPERATION_CALLS = Counter(
        "x402_operation_calls_total",
        "Gated operation calls",
        ["operation"],
    )


def _safe(metric: Any, **labels: str) -> Any | None:
    """Return a labeled child, or None when metrics are unavailable."""
    if metric is None:
        return None
    try:
        return metric.labels(**labels)
    except (ValueError, TypeError):  # unexpected label set — never break the flow
        return None


def record_challenge(operation: str, network: str) -> None:
    child = _safe(CHALLENGES_SENT, operation=operation or "unknown", network=network or "unknown")
    if child:
        child.inc()


def record_verify_success(network: str) -> None:
    child = _safe(VERIFY_SUCCESS, network=network or "unknown")
    if child:
        child.inc()


def record_verify_failure(network: str, reason: str) -> None:
    child = _safe(VERIFY_FAILURE, network=network or "unknown", reason=(reason or "unknown")[:64])
    if child:
        child.inc()


def record_settle(network: str, success: bool, amount_usd: float = 0.0, asset: str = "") -> None:
    child = _safe(SETTLE_TOTAL, network=network or "unknown")
    if child:
        child.inc()
    if success:
        child = _safe(SETTLE_SUCCESS, network=network or "unknown")
        if child:
            child.inc()
        if amount_usd > 0:
            child = _safe(
                SETTLEMENT_VOLUME_USD, network=network or "unknown", asset=asset or "unknown"
            )
            if child:
                child.inc(amount_usd)


def record_replay(network: str) -> None:
    child = _safe(REPLAY_DETECTED, network=network or "unknown")
    if child:
        child.inc()


def record_rpc_latency(network: str, method: str, seconds: float) -> None:
    child = _safe(RPC_LATENCY, network=network or "unknown", method=method or "unknown")
    if child:
        child.observe(max(0.0, seconds))


def set_facilitator_health(name: str, healthy: bool) -> None:
    child = _safe(FACILITATOR_HEALTH, facilitator=name or "unknown")
    if child:
        child.set(1 if healthy else 0)


def set_chain_active(network: str, active: bool) -> None:
    child = _safe(CHAIN_ACTIVE, network=network or "unknown")
    if child:
        child.set(1 if active else 0)


def record_operation_call(operation: str) -> None:
    child = _safe(OPERATION_CALLS, operation=operation or "unknown")
    if child:
        child.inc()
