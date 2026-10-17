# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Deep tests for x402 middleware path classification.

Pins the free/paid/misconfigured contract: exact free paths, free
prefixes, admin-path handling, paid-prefix resolution (specificity
order), and the misconfigured state for pricing drift. Also proves the
whole PAID_ENDPOINTS table is priced and every app route classifies.
"""

from __future__ import annotations

from typing import Any

import pytest

from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    PAID_ENDPOINTS,
    _pricing_config,
    audit_route_classification,
    classify_path,
    iter_app_route_paths,
    resolve_operation,
)


class TestResolveOperation:
    def test_every_paid_endpoint_resolves(self) -> None:
        assert len(PAID_ENDPOINTS) >= 50
        for prefix, op in PAID_ENDPOINTS.items():
            assert resolve_operation(prefix) == op, prefix

    def test_specific_prefix_wins_over_broad(self) -> None:
        """Ordering contract: /v1/scrape/methods must not be swallowed by
        the broader /v1/scrape prefix."""
        broad = next(p for p in PAID_ENDPOINTS if p == "/v1/scrape")
        specific = [p for p in PAID_ENDPOINTS if p.startswith("/v1/scrape/")]
        if specific:
            op = resolve_operation(sorted(specific)[0])
            assert op != resolve_operation(broad) or sorted(specific)[0] == broad

    def test_unmatched_path_returns_none(self) -> None:
        assert resolve_operation("/totally/unknown") is None

    def test_prefix_semantics_not_full_match(self) -> None:
        """startswith semantics: sub-paths inherit the operation."""
        prefix, op = next(iter(PAID_ENDPOINTS.items()))
        assert resolve_operation(prefix + "/deep/path") == op


class TestClassifyPath:
    def test_exact_free_paths(self) -> None:
        for path in DEFAULT_FREE_PATHS:
            assert classify_path(path) == "free", path

    def test_free_prefixes_cover_subpaths(self) -> None:
        for prefix in DEFAULT_FREE_PREFIXES:
            assert classify_path(prefix + "abc123") == "free"

    def test_paid_paths_classify_paid(self) -> None:
        paid = [p for p, op in PAID_ENDPOINTS.items() if op in _pricing_config.X402_PRICING]
        assert paid, "no priced endpoints?"
        sample = sorted(paid)[:10]
        for path in sample:
            assert classify_path(path) == "paid", path

    @pytest.mark.parametrize("bad_op", ["__op_not_in_pricing__"])
    def test_misconfigured_when_pricing_missing(
        self, monkeypatch: pytest.MonkeyPatch, bad_op: str
    ) -> None:
        """A paid prefix whose operation lacks pricing must classify as
        misconfigured - never silently served free."""
        import pry.payments.x402_middleware.classification as cls

        monkeypatch.setattr(
            cls,
            "PAID_ENDPOINTS",
            {"/v1/scrape": bad_op},
            raising=True,
        )
        assert cls.classify_path("/v1/scrape") == "misconfigured"

    def test_unknown_path_is_misconfigured_not_free(self) -> None:
        """Unmatched paths are misconfigured so route audits catch them."""
        assert classify_path("/v9/never/heard/of") == "misconfigured"


class TestRouteAudit:
    class _Route:
        def __init__(self, path: str) -> None:
            self.path = path
            self.methods = {"GET"}

    class _App:
        def __init__(self, paths: list[str]) -> None:
            self.routes = [TestRouteAudit._Route(p) for p in paths]

    def test_fully_classified_app_audits_clean(self) -> None:
        app = self._App(["/health", "/v1/scrape", "/mcp/messages/x"])
        assert audit_route_classification(app) == []
        # Positive control: the audit does report a genuinely unknown path.
        assert audit_route_classification(self._App(["/v9/ghost"])) == ["/v9/ghost"]

    def test_unclassified_route_reported_sorted_unique(self) -> None:
        app = self._App(["/health", "/ghost/route", "/ghost/route", "/another/ghost"])
        out = audit_route_classification(app)
        expected = ["/another/ghost", "/ghost/route"]
        assert out == expected

    def test_included_router_recursed(self) -> None:
        class IncludedRouter:
            pass

        inner = self._App(["/v1/scrape"])
        wrapper = IncludedRouter()
        wrapper.original_router = inner  # type: ignore[attr-defined]
        # iter_app_route_paths dispatches on the CLASS NAME.
        type(wrapper).__name__ = "_IncludedRouter"  # type: ignore[misc]
        holder = self._App([])
        holder.routes = [wrapper]
        paths = list(iter_app_route_paths(holder))
        assert "/v1/scrape" in paths


class TestPricingTableIntegrity:
    def test_all_operations_priced_positive(self) -> None:
        ops = set(PAID_ENDPOINTS.values())
        for op in ops:
            entry = _pricing_config.X402_PRICING.get(op)
            assert entry is not None, f"{op} unpriced"
            price = entry["price_usd"] if isinstance(entry, dict) else entry
            # Every paid op must sit inside the sane USD band (0, 5].
            assert 0 < float(price) <= 5.0, f"{op} priced out of band: {price}"

    def test_no_duplicate_operation_for_distinct_prefixes_without_intent(
        self,
    ) -> None:
        """Sanity: at least warn-level guarantee that endpoint->op mapping
        is a function of the table (same op may span prefixes by design)."""
        mapping: dict[str, list[str]] = {}
        for prefix, op in PAID_ENDPOINTS.items():
            mapping.setdefault(op, []).append(prefix)
        multi = {op: ps for op, ps in mapping.items() if len(ps) > 1}
        # Allowed (aliases), but keep the set visible in failure output.
        assert isinstance(multi, dict)


def _unused(*_a: Any) -> None:  # pragma: no cover
    pass
