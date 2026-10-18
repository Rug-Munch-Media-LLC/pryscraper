"""Pry — shared HTTP guards for the scraping routes.

Compliance block-list denial and audit sampling are API-layer concerns (they
touch the request scope, not the scraping engine), so they live here rather than
in ``pry.engine.scraping_service``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import random
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from pry.core.audit import audit_event


def audit_http(http_request: Request, operation: str, url: str, outcome: str) -> None:
    """Record an audit row. Host only — never the full URL or query string.

    Successes are sampled 1:100; denials and errors are always recorded.
    """
    if outcome == "success" and random.random() >= 0.01:  # noqa: S311 - sampling
        return
    record = http_request.scope.get("pry_api_key") or {}
    audit_event(
        "scrape_request",
        actor=str(record.get("key_id") or "")[:8],
        path=http_request.url.path,
        host=urlsplit(url).hostname or "",
        operation=operation,
        outcome=outcome,
    )


def deny_if_blocked(http_request: Request, operation: str, url: str) -> None:
    """451 before any fetch when the host is on the compliance block list."""
    from pry.core.domain_blocks import is_domain_blocked

    host = urlsplit(url).hostname or ""
    if host and is_domain_blocked(host):
        audit_http(http_request, operation, url, "denied")
        raise HTTPException(status_code=451, detail="Domain blocked for compliance reasons")
