# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Reachability verdicts as the scrape path reports them."""

from __future__ import annotations

import socket

from pry.engine import reachability_precheck as rp
from scripts.target_reachability import (
    Reachability,
    TargetProbe,
)
from tests.reachability_precheck_helpers import (
    _install,
    _stub,
)

HOST = "unreachable.invalid"
_URL = f"https://{HOST}/page"
#: A port with no listener, obtained by binding then releasing it so the
#: number is free and the connect is refused. A hard-coded port could collide
#: and quietly turn the test into a no-op.
_with_closed_port = socket.socket()
_with_closed_port.bind(("127.0.0.1", 0))
_CLOSED_PORT = int(_with_closed_port.getsockname()[1])
_with_closed_port.close()


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
