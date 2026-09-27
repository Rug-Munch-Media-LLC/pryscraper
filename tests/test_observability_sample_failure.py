"""A metric read failure must not be rendered as a real zero.

``_sample`` feeds ``metrics_summary()``, whose numbers are read by operators
as request / error / scrape totals. Before this was pinned, ANY exception in
``metric.collect()`` returned 0, so a broken metric read was indistinguishable
from a healthy idle process — a false all-clear, and a bogus
``error_rate_pct`` derived from it.

Only the structural errors prometheus_client raises on a malformed or absent
sample set may degrade to 0. Anything else propagates.

These tests use ``_sample``'s injected-metric parameter as the seam, so they
patch no module state and no fixture.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pry.core.observability import _sample


class _Exploding:
    """A metric whose read fails for a reason that is NOT structural."""

    def collect(self) -> Any:
        raise RuntimeError("prometheus registry exploded")


class _NoSampleGroups:
    """A metric that reports no sample groups — an IndexError path."""

    def collect(self) -> Any:
        return []


def test_unexpected_error_propagates_instead_of_reporting_zero() -> None:
    """A non-structural failure must surface, not read as "counter is zero"."""
    with pytest.raises(RuntimeError, match="prometheus registry exploded"):
        _sample("pry_requests_total", _Exploding())


def test_malformed_samples_do_not_fabricate_a_total() -> None:
    """A sample family with no ``.value`` attribute yields no fake number.

    ``TypeError`` is one of the *documented degradation* errors, so this
    returns 0 rather than raising. What matters is that the 0 comes from an
    explicit allowance, not from swallowing every error in sight.
    """
    corrupt = SimpleNamespace(
        collect=lambda: [SimpleNamespace(samples=[SimpleNamespace(name="pry_requests_total")])]
    )
    assert _sample("pry_requests_total", corrupt) == 0


def test_absent_sample_groups_degrade_to_zero() -> None:
    """An empty family is structural, so /metrics still renders."""
    assert _sample("pry_requests_total", _NoSampleGroups()) == 0


def test_missing_metric_reports_zero() -> None:
    """prometheus_client not installed is a legitimate zero, not a failure."""
    assert _sample("pry_requests_total", None) == 0


def test_synthetic_created_sample_is_excluded_and_count_is_read() -> None:
    """The correct path is unchanged: count is summed, ``_created`` ignored."""
    metric = SimpleNamespace(
        collect=lambda: [
            SimpleNamespace(
                samples=[
                    SimpleNamespace(name="pry_requests_total", value=7.0),
                    SimpleNamespace(name="pry_requests_total_created", value=1_700_000.0),
                ]
            )
        ]
    )
    assert _sample("pry_requests_total", metric) == 7
