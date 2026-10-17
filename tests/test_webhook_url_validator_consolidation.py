"""Consolidation test for the webhook URL validators.

``POST /v1/webhooks/test`` used to run its own SSRF check that resolved the host,
inspected the returned addresses, and then discarded them — so the delivery
client re-resolved the name at connect time and a rebinding resolver could hand
httpx a private address the check had never seen. ``pry.api.webhook_delivery``
already had the correct version (it returns a URL whose host is replaced by the
validated IP), and ``pry.api.routers.ai._watch_webhook`` already reused it.

These tests pin the consolidation: the router delegates to the pinned validator,
and the pinned one closes the rebinding window.

Each test names the mutation it kills.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import ipaddress
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from pry.api.routers.integrations.webhooks import _validate_webhook_url
from pry.api.webhook_delivery import _validate_url


def test_router_validator_rejects_private_targets() -> None:
    """Kills: the consolidation dropping the private-range check entirely (e.g.
    a delegate that swallows the rejection reason).
    """
    expected = {
        "http://169.254.169.254/latest/": "http only allowed for localhost",
        "https://127.0.0.1/hook": "host resolves to private/loopback IP: 127.0.0.1",
        "https://10.0.0.5/hook": "host resolves to private/loopback IP: 10.0.0.5",
    }
    for url, reason in expected.items():
        assert _validate_webhook_url(url) == reason, url


def test_router_validator_rejects_non_http_schemes() -> None:
    """Kills: a delegate that only checks the resolved address — a ``file://``
    URL never resolves, so an address-only check has nothing to reject it on.
    """
    assert _validate_webhook_url("file://evil.example.com/etc/passwd") == "unsupported scheme: file"


def test_router_validator_rejects_missing_host() -> None:
    """Kills: a delegate that loses the "no hostname" arm (e.g. only forwarding
    when a hostname parses), which would let a relative URL reach the client.
    """
    assert _validate_webhook_url("https:///nohost") == "missing hostname"


def test_router_validator_is_the_pinned_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills: reintroducing a router-local copy of the validator — a second
    implementation is free to drift back to the weaker, non-pinning form.

    The seam is the real module attribute, so this asserts on delegation rather
    than on a re-implementation of the checks.
    """
    seen: list[str] = []

    def _fake(url: str) -> tuple[None, str]:
        seen.append(url)
        return None, "sentinel rejection"

    monkeypatch.setattr("pry.api.webhook_delivery._validate_url", _fake)

    assert _validate_webhook_url("https://hook.example.com") == "sentinel rejection"
    expected = ["https://hook.example.com"]
    assert seen == expected, "the router did not delegate"


def test_pinned_validator_pins_the_resolved_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills: a validator that validates the resolved address and then returns
    the ORIGINAL url — the TOCTOU window this pinning exists to close. The
    returned URL's host must be the validated IP, so the client cannot re-resolve
    to something else at connect time.
    """
    resolved = "93.184.216.34"
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, 443)),
        ],
    )

    pinned, reason = _validate_url("https://hook.example.com/webhook")

    assert reason is None
    assert pinned is not None
    assert pinned == f"https://{resolved}/webhook", pinned
    ip = ipaddress.ip_address(resolved)
    assert not ip.is_private, resolved
    assert not ip.is_loopback, resolved
    assert not ip.is_link_local, resolved


def test_pinned_validator_rejects_a_rebinding_to_private_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kills: a pinning implementation that trusts only the FIRST resolved
    address. A resolver returning one public and one private address must be
    rejected, not silently narrowed to the public one.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )

    pinned, reason = _validate_url("https://hook.example.com/webhook")

    assert pinned is None
    assert reason is not None, "a private address in the answer was accepted"
    assert "127.0.0.1" in reason, reason
