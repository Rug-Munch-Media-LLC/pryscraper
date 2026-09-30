# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Reachability verdicts as the scrape path reports them."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any

from pry.engine import reachability_precheck as rp
from scripts.target_reachability import (
    Reachability,
    TargetProbe,
    blame_tier,
    classify,
    host_of,
)

if TYPE_CHECKING:
    import pytest


HOST = "unreachable.invalid"
_URL = f"https://{HOST}/page"
#: A port with no listener, obtained by binding then releasing it so the
#: number is free and the connect is refused. A hard-coded port could collide
#: and quietly turn the test into a no-op.
_with_closed_port = socket.socket()
_with_closed_port.bind(("127.0.0.1", 0))
_CLOSED_PORT = int(_with_closed_port.getsockname()[1])
_with_closed_port.close()


def _stub(probe: TargetProbe, host: str | None = None) -> Any:
    """A classifier whose probe is a fixed, already-observed fact.

    ``host`` defaults to :data:`HOST`; pass one to model a target whose cert
    covers its own name, or ``None`` to use the real extractor.
    """
    return type(
        "_Stub",
        (),
        {
            "host_of": staticmethod(host_of if host is None else lambda _url: host),
            "precheck_dns_and_tcp": staticmethod(lambda *_a, **_kw: probe),
            "classify": staticmethod(classify),
            "blame_tier": staticmethod(blame_tier),
        },
    )()


def _stub_raising(exc: BaseException) -> Any:
    """A classifier that blows up the way a real probe can."""

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise exc

    return type(
        "_Stub",
        (),
        {
            "host_of": staticmethod(lambda _url: HOST),
            "precheck_dns_and_tcp": staticmethod(_boom),
            "classify": staticmethod(classify),
            "blame_tier": staticmethod(blame_tier),
        },
    )()


def _install(monkeypatch: pytest.MonkeyPatch, stub: Any) -> None:
    monkeypatch.setattr(rp, "_load_classifier", lambda: stub)


# ── 1. An unreachable target is not a tier failure ────────────────────────


async def test_unreachable_target_is_never_blamed_on_the_tier(monkeypatch) -> None:
    _install(monkeypatch, _stub(TargetProbe(dns_ok=False, dns_error="no such host")))
    verdict = await rp.reachability_verdict(_URL)
    assert verdict["reachability"] == Reachability.UNREACHABLE
    assert verdict["blame_tier"] is False


async def test_tcp_refused_target_is_never_blamed_on_the_tier(monkeypatch) -> None:
    _install(monkeypatch, _stub(TargetProbe(dns_ok=True, tcp_ok=False, tcp_error="refused")))
    verdict = await rp.reachability_verdict(_URL)
    assert verdict["blame_tier"] is False


# ── 2. 403 keeps tier escalation alive (the regression that matters) ─────
#
# Driven through the real public ``classify``/``blame_tier`` (the probe is what
# is injected), so a defect in the taxonomy is caught here too — a wiring test
# must not be able to pass while the classifier itself is wrong.


def _refusing_403() -> TargetProbe:
    """A valid cert, then a status that means 'reachable, refusing US'."""
    return TargetProbe(
        dns_ok=True,
        tcp_ok=True,
        tls_completed=True,
        cert_subject="CN=site.example",
        cert_sans=("site.example",),
        cert_verified=True,
        http_status=403,
    )


async def test_403_is_refusing_and_keeps_tier_blame(monkeypatch) -> None:
    """403 is the site refusing US — a proxy tier exists precisely to answer it.

    Reporting it as UNREACHABLE would tell the operator to rebuild the ladder
    for a site that is up and talking. So REFUSING must survive the wiring.
    """
    _install(monkeypatch, _stub(_refusing_403(), host="site.example"))
    verdict = await rp.reachability_verdict("https://site.example/page")
    assert verdict["reachability"] == Reachability.REFUSING
    # blame_tier True: the chain did engage, so its failure is ours to own —
    # the signal that keeps tier escalation alive.
    assert verdict["blame_tier"] is True


async def test_403_is_not_reported_as_unreachable(monkeypatch) -> None:
    _install(monkeypatch, _stub(_refusing_403(), host="site.example"))
    verdict = await rp.reachability_verdict("https://site.example/page")
    assert verdict["reachability"] != Reachability.UNREACHABLE


# ── 2b. The shipped socket path, no classifier stubbed ───────────────────
#
# One honest end-to-end case. NOTE the limit this exposes: the live probe
# observes DNS+TCP only, so it can never reach REFUSING on its own — a 403
# needs an HTTP leg the precheck does not make. Refusing verdicts come from the
# scrape's own observed status, not from here. Loopback, so still offline.


async def test_the_live_path_reports_a_closed_port_as_unreachable() -> None:
    """The original incident's shape, with only the network left real."""
    verdict = await rp.reachability_verdict(f"https://127.0.0.1:{_CLOSED_PORT}/page", budget_s=1.0)
    assert verdict["reachability"] == Reachability.UNREACHABLE
    assert verdict["blame_tier"] is False


async def test_the_timeout_argument_is_never_mistaken_for_a_port(monkeypatch) -> None:
    """``precheck_dns_and_tcp``'s second positional is the PORT, not the timeout.

    Passing the timeout positionally dialled it as a port number, and a probe
    aimed at a port nobody asked for reports a fabricated UNREACHABLE. Keyword
    args are the only safe call, so the call SHAPE is pinned here.
    """
    seen: dict[str, Any] = {}

    def _probe(host: str, port: int = 443, timeout: float = 5.0) -> TargetProbe:
        seen.update(host=host, port=port, timeout=timeout)
        return TargetProbe(dns_ok=True, tcp_ok=False)

    _install(
        monkeypatch,
        type(
            "_Recording",
            (),
            {
                "host_of": staticmethod(host_of),
                "precheck_dns_and_tcp": staticmethod(_probe),
                "classify": staticmethod(classify),
                "blame_tier": staticmethod(blame_tier),
            },
        )(),
    )
    await rp.reachability_verdict("https://site.example/p", budget_s=1.5)
    # No port in the URL, so the https default is dialled.
    assert seen == {"host": "site.example", "port": 443, "timeout": 1.5}


async def test_the_probe_dials_the_port_the_scrape_requests(monkeypatch) -> None:
    """A precheck aimed at the wrong port reports a fabricated UNREACHABLE.

    The verdict must be about the endpoint actually being requested, so an
    explicit port in the URL wins over the default.
    """
    seen: dict[str, Any] = {}

    def _probe(host: str, port: int = 443, timeout: float = 5.0) -> TargetProbe:
        seen.update(host=host, port=port, timeout=timeout)
        return TargetProbe(dns_ok=True, tcp_ok=False)

    _install(
        monkeypatch,
        type(
            "_Recording",
            (),
            {
                "host_of": staticmethod(host_of),
                "precheck_dns_and_tcp": staticmethod(_probe),
                "classify": staticmethod(classify),
                "blame_tier": staticmethod(blame_tier),
            },
        )(),
    )
    await rp.reachability_verdict("https://site.example:8443/p", budget_s=1.5)
    assert seen == {"host": "site.example", "port": 8443, "timeout": 1.5}


# ── 3. UNKNOWN stays distinct from UNREACHABLE ────────────────────────────


async def test_unknown_from_no_readable_cert_is_distinct_from_unreachable(
    monkeypatch,
) -> None:
    """The original incident's exact shape: handshake finished, no cert.

    The socket accepted us, so accusing the target would be unwarranted.
    """
    _install(monkeypatch, _stub(TargetProbe(dns_ok=True, tcp_ok=True, tls_completed=True)))
    verdict = await rp.reachability_verdict(_URL)
    assert verdict["reachability"] == Reachability.UNKNOWN
    assert verdict["reachability"] != Reachability.UNREACHABLE
    assert verdict["blame_tier"] is False
