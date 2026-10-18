"""Pry - Apify Actor Factory: web-capability item processors.

These processors back the specialised actors that used to advertise more
than the generic runner delivered. Each one either performs the real work
(screenshot shaping, PDF extraction, TLS probing, crawl bookkeeping) or
returns an explicit ``unavailable`` field instead of inventing data.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse


def process_screenshot(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Describe the render actually produced by WebCapabilityRunner."""
    if item.get("status") != "ok":
        return item
    item["full_page"] = bool(options.get("full_page", True))
    item["viewport_width"] = int(options.get("viewport_width", 1280) or 1280)
    item["screenshot_format"] = "png"
    item["screenshot_bytes"] = int(item.get("screenshot_bytes", 0) or 0)
    return item


def process_crawl(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Record crawl bookkeeping for one expanded page."""
    depth = state.get("depths", {}).get(url, 0)
    item["depth"] = int(depth)
    item["links_found"] = len(item.get("discovered_links") or [])
    return item


def process_pdfdoc(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Normalise PDF extraction output (text, page count, method)."""
    parsed = item.get("document") or {}
    item["document_type"] = item.get("document_type", "html")
    item["page_count"] = int(parsed.get("page_count", 0) or 0)
    item["document_text"] = parsed.get("text", "") or item.get("content", "")
    item["parser_method"] = parsed.get("method_used", "") or "html"
    if item.get("document_type") != "pdf" and item.get("status") == "ok":
        item["ocr_used"] = False
    return item


def _cert_days_left(cert: dict[str, Any]) -> int | None:
    expires = cert.get("notAfter")
    if not expires:
        return None
    not_after = ssl.cert_time_to_seconds(expires)
    return int((not_after - datetime.now(UTC).timestamp()) // 86400)


def _probe_tls(host: str) -> tuple[dict[str, Any], str]:
    """Live TLS handshake; returns (peer certificate, protocol version)."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return (tls.getpeercert() or {}, tls.version() or "")


def process_sslcert(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Probe the TLS certificate of one host (real handshake, no fake data)."""
    host = (urlparse(url).hostname or "").strip()
    warn_days = int(options.get("warn_days", 14) or 14)
    item["host"] = host
    item["warn_days"] = warn_days
    if not host:
        item["status"] = "error"
        item["error"] = "invalid_host"
        return item
    try:
        cert, protocol = _probe_tls(host)
    except (OSError, ssl.SSLError) as exc:
        item["status"] = "error"
        item["error"] = f"tls_error: {str(exc)[:120]}"
        item["certificate"] = {}
        return item
    days_left = _cert_days_left(cert)
    issuer = dict(x[0] for x in cert.get("issuer", ()) if x)
    subject = dict(x[0] for x in cert.get("subject", ()) if x)
    soon = bool(days_left is not None and days_left <= warn_days)
    item["status"] = "ok"
    item["certificate"] = {
        "issuer": issuer.get("organizationName", ""),
        "common_name": subject.get("commonName", ""),
        "expires_at": cert.get("notAfter", ""),
        "days_left": days_left,
        "tls_version": protocol,
        "expiring_soon": soon,
    }
    item["days_left"] = days_left
    item["expiring_soon"] = soon
    return item


def process_tokensafety(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Return an explicit unavailable marker - no on-chain risk feed here."""
    item["status"] = "unavailable"
    item["invalid"] = True
    item["unavailable"] = "token_risk_feed_not_configured"
    item["reason"] = (
        "This actor has no on-chain risk provider wired in. It does not "
        "invent risk scores; connect a risk API to enable screening."
    )
    item["signals"] = []
    return item


def process_sanctions(
    url: str, item: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Return an explicit unavailable marker - no sanctions list bundled."""
    item["status"] = "unavailable"
    item["invalid"] = True
    item["unavailable"] = "sanctions_data_not_bundled"
    item["reason"] = (
        "No OFAC/EU watchlist snapshot ships with this actor. It will not "
        "fabricate matches; supply a data source to enable screening."
    )
    item["matches"] = []
    return item
