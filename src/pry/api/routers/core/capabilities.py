"""Pry — Capabilities router (deployment capability detection).

Exposes ``GET /v1/capabilities``, which reports what the deployment actually
supports (browsers, anti-bot tooling, Tor, proxies, CAPTCHA solving, LLM
providers, storage) plus actionable recommendations, so Pry can self-configure
instead of silently degrading.

Import-safe: :mod:`capabilities` is imported lazily inside the handler, so
this module can be imported (and this router included) before the detection
logic is wired into ``api.py``.

The endpoint is intentionally synchronous — FastAPI runs sync handlers in a
threadpool, keeping the short TCP probes (DB / Redis / SOCKS) off the event
loop.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["Capabilities"])


@router.get("/v1/capabilities", summary="Detect deployment capabilities")
def get_capabilities() -> dict[str, Any]:
    """Return a structured report of what this deployment actually supports."""
    from pry.api.capabilities import detect_capabilities

    return {"success": True, "data": detect_capabilities()}
