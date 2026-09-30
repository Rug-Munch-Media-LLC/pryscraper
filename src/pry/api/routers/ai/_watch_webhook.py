"""Fire-and-forget webhook delivery for the /v1/watch sink, split out of ``analysis``.

``analysis`` owns the request/response surface of the AI router; this module owns
the one outbound request that router makes on a watch event, plus the task
plumbing that makes its outcome observable.

Three invariants this module exists to hold:

1. **The free ``/v1/watch`` route cannot be turned into an SSRF primitive.** The
   ``webhook`` body parameter is fully caller-controlled and the POST is made
   server-side, so unguarded it is a blind internal port-scan / internal-service
   poke (fire-and-forget: the caller only observes timing).
2. **Validation and connect must agree on the address.** We reuse the
   DNS-pinning validator from :mod:`pry.api.webhook_delivery` rather than adding
   a weaker second implementation — it returns a URL whose host is replaced by
   the validated IP, closing the DNS-rebinding TOCTOU window between the two.
3. **A fire-and-forget failure is never silent.** ``asyncio.create_task`` attaches
   no done-callback, so an exception escaping the coroutine vanishes while the
   request still returns 200. The callback here logs the outcome and retrieves
   the exception so asyncio does not also report it as unhandled.

No response body and no exception text is ever logged: webhook URLs routinely
carry a secret in the path or query, and failure text can echo request data.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any

logger = logging.getLogger("pry.api.routers.ai.analysis")
"""The watch-webhook log records are attributed to the ANALYSIS ROUTER, not to this
module. The logger name is observable behaviour -- it is what operators filter on
and what the regression tests assert against -- so moving the functions out of
``analysis.py`` must not rename the stream they emit into."""


def _schedule_watch_webhook(
    webhook: str, url: str, diff_result: dict[str, Any]
) -> asyncio.Task[None]:
    """Start the fire-and-forget watch webhook and make its outcome observable.

    ``asyncio.create_task`` attaches no done-callback, so an exception escaping
    the coroutine is swallowed silently — the request still returns 200 and the
    delivery failure is invisible. We register a done-callback that logs the
    outcome and retrieves the exception so asyncio does not report it as an
    unhandled task exception.

    Returns:
        The scheduled task, so callers and tests can await it.
    """
    from pry.api.routers.ai.analysis import _fire_watch_webhook

    task = asyncio.create_task(_fire_watch_webhook(webhook, url, diff_result))
    task.add_done_callback(_log_watch_webhook_outcome)
    return task


def _log_watch_webhook_outcome(task: asyncio.Task[None]) -> None:
    """Log a completed watch-webhook task. Never logs the response body."""
    if task.cancelled():
        logger.info("watch_webhook_cancelled")
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "watch_webhook_task_failed",
            extra={"url": task.get_name(), "error_type": type(error).__name__},
        )
        return
    logger.info("watch_webhook_task_completed")


async def _fire_watch_webhook(webhook: str, url: str, diff_result: dict[str, Any]) -> None:
    """Fire a webhook notification for watch events.

    SSRF guard: ``webhook`` is fully caller-controlled and the request is made
    server-side, so without this gate the free ``/v1/watch`` route is a blind
    internal port-scan primitive (fire-and-forget: the caller only sees timing).
    We reuse the DNS-pinning validator from :mod:`pry.api.webhook_delivery`
    rather than adding a weaker second implementation — it returns a URL whose
    host is replaced by the validated IP, closing the DNS-rebinding TOCTOU
    window between validation and connect. The response body is never logged.
    """
    import httpx

    from pry.api.client import get_client
    from pry.api.webhook_delivery import _validate_url

    pinned_url, rejection = _validate_url(webhook)
    if rejection:
        logger.warning(
            "watch_webhook_url_rejected",
            extra={"watch_url": url, "reason": rejection},
        )
        return
    try:
        client = await get_client()
        response = await client.post(
            pinned_url,
            json={"event": "watch_update", "url": url, "data": diff_result},
            timeout=10,
            follow_redirects=False,
            extensions={"sni_hostname": urllib.parse.urlparse(webhook).hostname or ""},
        )
        logger.info(
            "watch_webhook_delivered",
            extra={"watch_url": url, "status_code": response.status_code},
        )
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning(
            "watch_webhook_failed",
            extra={"watch_url": url, "error_type": type(e).__name__},
        )
