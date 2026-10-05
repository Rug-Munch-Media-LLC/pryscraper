# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""SSRF rejection tests for the /v1/watch webhook sink (split 1 of 2).

The ``webhook`` body parameter of the FREE (unauthenticated) ``/v1/watch``
route reaches ``_fire_watch_webhook``, which performs a server-side POST.
Unguarded, that is a blind internal port-scan / internal-service-poke primitive
(fire-and-forget: the caller only observes timing).

This half pins that an attack URL is refused BEFORE any request is attempted,
that the refusal is logged, and that the log does not echo the credential-bearing
webhook URL. The legitimate-delivery and outcome-observability cases are in
``test_w0_watch_webhook_delivery.py``.

Each test names the mutation it kills. No test here makes a real network call:
DNS is stubbed in ``w0_watch_fixtures._stub_dns`` and the transport is mocked
with ``respx``.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from pry.api.routers.ai.analysis import _fire_watch_webhook
from tests.w0_watch_fixtures import DIFF, _stub_dns

# ---------------------------------------------------------------------------
# Rejection BEFORE any request is made
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "webhook", "dns"),
    [
        # Cloud metadata. Resolves to link-local -> rejected after DNS, before
        # httpx is even constructed. Kills the mutation "delete the validate
        # call from _fire_watch_webhook".
        ("cloud_metadata", "http://169.254.169.254/latest/meta-data/", {}),
        # Loopback on a port the attacker varies to port-scan. Same mutation.
        (
            "loopback",
            "http://127.0.0.1:6379/",
            {"127.0.0.1": "127.0.0.1"},
        ),
        # RFC1918. Same mutation.
        ("rfc1918", "http://10.0.0.5/internal", {"10.0.0.5": "10.0.0.5"}),
        # Non-HTTP scheme. Kills the mutation "accept any scheme" — a file://
        # read would be worse than the SSRF it is a symptom of.
        ("file_scheme", "file:///etc/passwd", {}),
    ],
)
async def test_rejected_before_any_request(
    label: str, webhook: str, dns: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Attack URLs are refused and NO http request is ever attempted."""
    with _stub_dns(dns), respx.mock(assert_all_called=False) as router:
        # A catch-all route: if any request is made, this fires and the
        # `not router.routes or not router.routes[0].called` assert below
        # fails. This is what makes the test prove "before any request".
        router.route(host="*", path="*").mock(return_value=httpx.Response(200))
        with caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
            await _fire_watch_webhook(webhook, "https://target.example", DIFF)

    made = [r for r in router.routes if r.called]
    assert not made, f"{label}: request escaped the validator ({len(made)} made)"


async def test_metadata_rejection_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A rejection is visible in logs, not a silent no-op.

    Kills the mutation "rejection returns without logging".
    """
    with _stub_dns({}), caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
        await _fire_watch_webhook(
            "http://169.254.169.254/latest/meta-data/", "https://target.example", DIFF
        )
    assert "watch_webhook_url_rejected" in caplog.text


async def test_rejection_log_omits_secret_url(caplog: pytest.LogCaptureFixture) -> None:
    """The rejection log must not echo the credential-bearing webhook URL.

    Many webhook URLs carry a secret in the path or query. Kills the mutation
    "log the raw user-supplied webhook URL". Asserts on ``caplog.records``
    rather than ``caplog.text`` — the text form truncates long records, which
    hides exactly the leak we are testing for.
    """
    secret = "tok"
    webhook = f"http://169.254.169.254/latest/meta-data/?token={secret}"
    with _stub_dns({}), caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
        await _fire_watch_webhook(webhook, "https://target.example", DIFF)
    records = [r for r in caplog.records if r.name == "pry.api.routers.ai.analysis"]
    assert records, "no log record emitted for the rejection"
    for record in records:
        blob = repr(record.__dict__)
        assert secret not in blob, f"secret leaked into log record: {blob}"
        assert webhook not in blob, "raw webhook URL leaked into log record"
