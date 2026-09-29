# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the target reachability precheck.

Every case injects observed facts. No test opens a socket, so this file runs
offline and stays deterministic.
"""

from __future__ import annotations

import pytest

from scripts.target_reachability import (
    Failure,
    Reachability,
    TargetProbe,
    blame_tier,
    classify,
    classify_tls,
    host_of,
)

HOST = "blog.soliditylang.com"


def _tls_ok(**kw) -> TargetProbe:
    base = {
        "dns_ok": True,
        "tcp_ok": True,
        "tls_completed": True,
        "cert_subject": "CN=soliditylang.com",
        "cert_sans": ("*.soliditylang.com", "soliditylang.com"),
        "cert_verified": True,
    }
    return TargetProbe(**{**base, **kw})


# ── The false "verify return code 0" guard ────────────────────────────────
# The exact host in the original incident: handshake ends, NO cert presented,
# openssl still prints "Verify return code: 0".


def test_no_peer_certificate_is_unreachable_not_healthy():
    probe = TargetProbe(dns_ok=True, tcp_ok=True, tls_completed=True, cert_subject=None)
    assert classify_tls(probe, HOST) is Failure.TLS_NO_PEER_CERT


def test_handshake_completed_alone_never_proves_reachability():
    """A completed handshake with no SAN is still a failure — the real trap."""
    probe = TargetProbe(tls_completed=True, cert_subject="CN=somewhere.else")
    assert classify_tls(probe, HOST) is Failure.TLS_HOSTNAME_MISMATCH


def test_missing_subject_is_distinct_from_missing_san():
    without_san = TargetProbe(tls_completed=True, cert_subject="CN=soliditylang.com")
    assert classify_tls(without_san, HOST) is Failure.TLS_HOSTNAME_MISMATCH


def test_incomplete_handshake_is_its_own_verdict():
    probe = TargetProbe(tls_completed=False, tls_error="tlsv1 unrecognized name")
    assert classify_tls(probe, HOST) is Failure.TLS_HANDSHAKE
    assert classify(probe, HOST) is Reachability.UNREACHABLE


def test_no_peer_cert_and_incomplete_handshake_are_not_collapsed():
    """The two TLS failure shapes must stay distinguishable to be actionable."""
    no_cert = TargetProbe(tls_completed=True, cert_subject=None)
    assert classify_tls(no_cert, HOST) is not classify_tls(TargetProbe(tls_completed=False), HOST)


# ── SAN matching ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sans", "expected"),
    [
        (("blog.soliditylang.com",), Failure.NONE),
        (("*.soliditylang.com",), Failure.NONE),
        (("BLOG.SOLIDITYLANG.COM",), Failure.NONE),  # case-insensitive
        (("soliditylang.com",), Failure.TLS_HOSTNAME_MISMATCH),
        # A wildcard covers one label only: the classic over-match bug.
        (("*.com",), Failure.TLS_HOSTNAME_MISMATCH),
        (("*.*.com",), Failure.TLS_HOSTNAME_MISMATCH),
        ((), Failure.TLS_HOSTNAME_MISMATCH),
    ],
)
def test_san_matching(sans, expected):
    assert classify_tls(_tls_ok(cert_sans=sans), HOST) is expected


def test_ip_target_requires_exact_san_not_wildcard():
    probe = _tls_ok(cert_sans=("*.0.0.1",))
    assert classify_tls(probe, "10.0.0.1") is Failure.TLS_HOSTNAME_MISMATCH


def test_wildcard_does_not_match_without_a_label_boundary():
    """``*.soliditylang.com`` must not cover ``evilsoliditylang.com``."""
    probe = _tls_ok(cert_sans=("*.soliditylang.com",))
    assert classify_tls(probe, "evilsoliditylang.com") is Failure.TLS_HOSTNAME_MISMATCH


def test_wildcard_covers_exactly_one_label():
    probe = _tls_ok(cert_sans=("*.soliditylang.com",))
    assert classify_tls(probe, "a.b.soliditylang.com") is Failure.TLS_HOSTNAME_MISMATCH


def test_unverified_chain_still_blocks():
    probe = _tls_ok(cert_verified=False)
    assert classify_tls(probe, HOST) is Failure.TLS_HANDSHAKE


# ── Transport: unreachable is distinct from refusing ──────────────────────


def test_dns_failure_is_unreachable():
    probe = TargetProbe(dns_ok=False, dns_error="Name or service not known")
    assert classify(probe, HOST) is Reachability.UNREACHABLE


def test_tcp_refusal_is_unreachable():
    probe = TargetProbe(dns_ok=True, tcp_ok=False, tcp_error="Connection refused")
    assert classify(probe, HOST) is Reachability.UNREACHABLE


@pytest.mark.parametrize("status", [401, 403, 407, 429, 451])
def test_refusal_statuses_are_reachable_and_refusing(status):
    """403 means reachable and refusing US — that is what a proxy tier is FOR."""
    assert classify(_tls_ok(http_status=status), HOST) is Reachability.REFUSING


def test_403_is_never_unreachable():
    assert classify(_tls_ok(http_status=403), HOST) is not Reachability.UNREACHABLE


def test_2xx_is_reachable():
    assert classify(_tls_ok(http_status=200), HOST) is Reachability.REACHABLE


def test_5xx_is_unreachable():
    assert classify(_tls_ok(http_status=503), HOST) is Reachability.UNREACHABLE


def test_no_observation_is_unknown_not_a_fault():
    probe = TargetProbe(dns_ok=True, tcp_ok=True, tls_completed=True)
    assert classify_tls(probe, HOST) is Failure.TLS_NO_PEER_CERT
    assert classify(probe, HOST) is Reachability.UNKNOWN


def test_completed_handshake_without_readable_cert_is_not_accused():
    """A handshake that finished with nothing to inspect is absence of evidence.

    We cannot say the target is broken, and we cannot say it is healthy, so
    we must not let either verdict leak into a tier fault.
    """
    probe = TargetProbe(dns_ok=True, tcp_ok=True, tls_completed=True, cert_subject=None)
    assert classify(probe, HOST) is Reachability.UNKNOWN
    assert blame_tier(classify(probe, HOST)) is False


def test_empty_probe_is_unknown():
    probe = TargetProbe()
    assert probe.observed is False
    assert classify(probe, HOST) is Reachability.UNKNOWN


# ── The central judgement: unreachable is NOT a scrape failure ────────────


def test_unreachable_is_never_blamed_on_the_tier():
    assert blame_tier(Reachability.UNREACHABLE) is False


def test_unknown_is_never_blamed_on_the_tier():
    """We did not observe enough to accuse anyone."""
    assert blame_tier(Reachability.UNKNOWN) is False


@pytest.mark.parametrize("state", [Reachability.REACHABLE, Reachability.REFUSING])
def test_engaged_tier_owns_its_failures(state):
    assert blame_tier(state) is True


# ── Host extraction ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://blog.soliditylang.com/", "blog.soliditylang.com"),
        ("https://BLOG.SolidityLang.com/x?y=1", "blog.soliditylang.com"),
        ("https://blog.soliditylang.com:8443/", "blog.soliditylang.com"),
    ],
)
def test_host_of(url, expected):
    assert host_of(url) == expected
