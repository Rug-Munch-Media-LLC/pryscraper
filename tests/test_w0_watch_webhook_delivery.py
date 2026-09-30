# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Legitimate delivery + outcome observability for the /v1/watch webhook (split 2 of 2).

Split from ``test_w0_watch_webhook_ssrf.py`` (258 lines, over the 200-line cap).
The rejection half — that an attack URL is refused before any request is
attempted, and that the refusal is logged without echoing the secret — is in
``test_w0_watch_webhook_ssrf.py``.

This half holds the other direction: a legitimate public webhook must still be
delivered, it must go to the DNS-PINNED ip rather than the re-resolved
hostname, and the fire-and-forget task must be OBSERVED so a delivery failure
can never be silent.

Each test names the mutation it kills. No test here makes a real network call:
DNS is stubbed in ``w0_watch_fixtures._stub_dns`` and the transport is mocked
with ``respx``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import respx

from pry.api.routers.ai import analysis
from pry.api.routers.ai.analysis import _fire_watch_webhook
from tests.w0_watch_fixtures import DIFF, PUBLIC_IP, PUBLIC_WEBHOOK, _stub_dns

if TYPE_CHECKING:
    import pytest


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
        await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", DIFF)
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
        await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", DIFF)
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
                "https://rebind.example.com/cb", "https://target.example", DIFF
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
            await _fire_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", DIFF)
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
        task = analysis._schedule_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", DIFF)
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
            task = analysis._schedule_watch_webhook(PUBLIC_WEBHOOK, "https://target.example", DIFF)
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
    assert "watch_webhook_task_completed" in caplog.text
