# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""SSRF + observability tests for the /v1/watch webhook sink.

The ``webhook`` body parameter of the FREE (unauthenticated) ``/v1/watch``
route reaches ``_fire_watch_webhook``, which performs a server-side POST.
Unguarded, that is a blind internal port-scan / internal-service-poke primitive
(fire-and-forget: the caller only observes timing).

Each test names the mutation it kills. No test here makes a real network call:
DNS is stubbed in ``_stub_dns`` and the transport is mocked with ``respx``.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.api.routers.ai import analysis
from pry.api.routers.ai.analysis import _fire_watch_webhook

# A routable-looking public IP used as the stubbed DNS answer. Nothing ever
# connects to it — respx intercepts at the transport layer.
PUBLIC_IP = "93.184.216.34"
PUBLIC_WEBHOOK = "https://hooks.example.com/services/T00/B00/XXXX"

_DIFF: dict[str, Any] = {"status": "registered", "url": "https://target.example", "version": 1}


def _stub_dns(mapping: dict[str, str]) -> Any:
    """Resolve ONLY the given hostnames; anything else fails to resolve.

    Uses a real ``socket.getaddrinfo`` seam (the same call the validator makes)
    rather than patching the validator, so the DNS-pinning logic under test
    stays real.
    """

    def fake_getaddrinfo(host: str, port: object, *args: object, **kwargs: object) -> list[Any]:
        try:
            ip = mapping[host]
        except KeyError:
            raise socket.gaierror(f"stub: refusing to resolve {host!r}") from None
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]  # type: ignore[misc]

    return patch("socket.getaddrinfo", side_effect=fake_getaddrinfo)


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
            await _fire_watch_webhook(webhook, "https://target.example", _DIFF)

        made = [r for r in router.routes if r.called]
        assert not made, f"{label}: request escaped the validator ({len(made)} made)"


async def test_metadata_rejection_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A rejection is visible in logs, not a silent no-op.

    Kills the mutation "rejection returns without logging".
    """
    with _stub_dns({}), caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
        await _fire_watch_webhook(
            "http://169.254.169.254/latest/meta-data/", "https://target.example", _DIFF
        )
    assert "watch_webhook_url_rejected" in caplog.text


async def test_rejection_log_omits_secret_url(caplog: pytest.LogCaptureFixture) -> None:
    """The rejection log must not echo the credential-bearing webhook URL.

    Many webhook URLs carry a secret in the path or query. Kills the mutation
    "log the raw user-supplied webhook URL". Asserts on ``caplog.records``
    rather than ``caplog.text`` — the text form truncates long records, which
    hides exactly the leak we are testing for.
    """
    secret = "s3cr3t-token-value"
    webhook = f"http://169.254.169.254/latest/meta-data/?token={secret}"
    with _stub_dns({}), caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
        await _fire_watch_webhook(webhook, "https://target.example", _DIFF)
    records = [r for r in caplog.records if r.name == "pry.api.routers.ai.analysis"]
    assert records, "no log record emitted for the rejection"
    for record in records:
        blob = repr(record.__dict__)
        assert secret not in blob, f"secret leaked into log record: {blob}"
        assert webhook not in blob, "raw webhook URL leaked into log record"


# ---------------------------------------------------------------------------
# Legitimate use keeps working
# ---------------------------------------------------------------------------


async def test_public_webhook_still_fires() -> None:
    """A normal public https webhook MUST still be delivered.

    Kills the mutations "reject all webhooks" and "break the DNS pinning".
    """
    with _stub_dns({"hooks.example.com": PUBLIC_IP}), respx.mock(assert_all_called=True) as router:
        # The validator pins the host to the validated IP, so that is the
        # URL httpx connects to. SNI/Host keep the original hostname.
        route = router.post(f"https://{PUBLIC_IP}/services/T00/B00/XXXX").mock(
            return_value=httpx.Response(200)
        )
        await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", _DIFF)
        assert route.called, "public webhook was NOT delivered"
        body = route.calls.last.request.content
        assert b"watch_update" in body


async def test_public_webhook_is_delivered_to_the_pinned_ip() -> None:
    """The request goes to the PINNED IP, not the re-resolved hostname.

    Kills the mutation "revert to posting to the raw hostname", which
    re-opens the DNS-rebinding TOCTOU window.
    """
    # assert_all_mocked (not assert_all_called): an unexpected request fails the
    # test, but the decoy hostname route is EXPECTED to go uncalled — that is
    # the whole assertion.
    with (
        _stub_dns({"hooks.example.com": PUBLIC_IP}),
        respx.mock(assert_all_called=False, assert_all_mocked=True) as router,
    ):
        route = router.post(f"https://{PUBLIC_IP}/services/T00/B00/XXXX").mock(
            return_value=httpx.Response(200)
        )
        hostname_route = router.post(PUBLIC_WEBHOOK).mock(return_value=httpx.Response(200))
        await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", _DIFF)
        assert route.called, "webhook was not sent to the pinned IP"
        assert not hostname_route.called, "hostname was re-resolved at connect time"


async def test_rebinding_hostname_rejected(caplog: pytest.LogCaptureFixture) -> None:
    """A public-looking hostname that resolves to loopback is rejected.

    This is the DNS-rebinding payload: a hostname that passes a naive
    "is the hostname a private literal?" check but resolves inside.
    Kills the mutation "validate only the literal IP, skip DNS".
    """
    with (
        _stub_dns({"rebind.example.com": "127.0.0.1"}),
        respx.mock(assert_all_called=False) as router,
    ):
        router.route(host="*", path="*").mock(return_value=httpx.Response(200))
        with caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
            await _fire_watch_webhook(
                "https://rebind.example.com/cb", "https://target.example", _DIFF
            )
        assert not [r for r in router.routes if r.called]
    assert "watch_webhook_url_rejected" in caplog.text


# ---------------------------------------------------------------------------
# Outcome observability (the unobserved create_task)
# ---------------------------------------------------------------------------


async def test_transport_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """A network error is logged with its type, not swallowed or f-stringed.

    Kills the mutation "revert to the bare `except: logger.exception`" and
    any variant that leaks the response body into the log.
    """
    with _stub_dns({"hooks.example.com": PUBLIC_IP}), respx.mock(assert_all_called=True) as router:
        router.post(f"https://{PUBLIC_IP}/services/T00/B00/XXXX").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"):
            await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", _DIFF)
    assert "watch_webhook_failed" in caplog.text
    records = [r for r in caplog.records if r.name == "pry.api.routers.ai.analysis"]
    for record in records:
        assert "refused" not in repr(record.__dict__), "exception text leaked into the log"


async def test_scheduler_registers_done_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fire-and-forget task is OBSERVED: a raising coroutine is logged.

    A bare ``asyncio.create_task`` with no done-callback lets an exception
    vanish. Kills the mutation "call asyncio.create_task directly with no
    done callback" — the class of bug where a delivery failure is invisible.
    """
    boom = httpx.ConnectError("task-level failure")
    with (
        caplog.at_level(logging.WARNING, logger="pry.api.routers.ai.analysis"),
        patch.object(analysis, "_fire_watch_webhook", side_effect=boom) as fire_spy,
    ):
        task = analysis._schedule_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", _DIFF)
        await asyncio.gather(task, return_exceptions=True)
        # Let the done-callback (scheduled via call_soon) run.
        await asyncio.sleep(0)
    assert fire_spy.called, "fire-and-forget coroutine never ran"
    assert task.done()
    # The callback retrieved the exception (task.exception() no longer raises)
    # and logged it — an unobserved task would satisfy neither.
    assert task.exception() is boom
    assert "watch_webhook_task_failed" in caplog.text
    assert "task-level failure" not in caplog.text, "exception text leaked into the log"


async def test_scheduler_logs_success_outcome(caplog: pytest.LogCaptureFixture) -> None:
    """A successful delivery is logged too, so 'delivered' is provable.

    Kills the mutation "callback only logs the failure branch".
    """
    with _stub_dns({"hooks.example.com": PUBLIC_IP}), respx.mock(assert_all_called=True) as router:
        router.post(f"https://{PUBLIC_IP}/services/T00/B00/XXXX").mock(
            return_value=httpx.Response(200)
        )
        with caplog.at_level(logging.INFO, logger="pry.api.routers.ai.analysis"):
            task = analysis._schedule_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", _DIFF)
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
    assert "watch_webhook_task_completed" in caplog.text
