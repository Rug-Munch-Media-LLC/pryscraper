"""Live-probe behaviour of the reachability precheck.

Split from tests/test_reachability_precheck_verdicts.py to clear the 200-line cap.
The verdict-classification tests stay there; the tests that exercise the real
socket dial live here, because they need the closed-port fixture and the loader
plumbing that goes with it.
"""

from __future__ import annotations

import socket
from typing import Any

from pry.engine import reachability_precheck as rp
from scripts.target_reachability import (
    Reachability,
    TargetProbe,
    blame_tier,
    classify,
    host_of,
)
from tests.reachability_precheck_helpers import (
    _install,
    _stub,
)

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


HOST = "unreachable.invalid"
_URL = f"https://{HOST}/page"

# A port nothing listens on: bind one, learn its number, release it. Any connect
# to it is refused, which is the deterministic stand-in for an unreachable host.
_with_closed_port = socket.socket()
_with_closed_port.bind(("127.0.0.1", 0))
_CLOSED_PORT = int(_with_closed_port.getsockname()[1])
_with_closed_port.close()


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
    expected = {"host": "site.example", "port": 443, "timeout": 1.5}
    assert seen == expected


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
    expected = {"host": "site.example", "port": 8443, "timeout": 1.5}
    assert seen == expected


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
