"""Pry — Live OpenAPI spec generator for AI agent integration.

Serves the LIVE spec generated from the running FastAPI app so the
AI-consumer surface (GPT Actions, MCP configs) can never drift from the
actual registered routes. The checked-in openapi.json is NOT read here —
it exists only as a static snapshot for tooling/CI.

This module intentionally sits OUTSIDE pry.api.ai_plugin: it imports the
full app (every domain), so only app-level callers (routers/core/system)
may import it — domain routers must not, or the domain-independence
contract breaks.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_openapi_spec() -> dict[str, Any]:
    """Get the OpenAPI spec for AI agent integration."""
    try:
        # Lazy import: `api` is heavy and importing it at module load would
        # couple this module to the full app (and risk a circular import).
        from pry.api.api import app

        return app.openapi()
    except Exception as e:  # noqa: BLE001
        logger.error("openapi_spec_generation_failed", extra={"error": str(e)})
        return {"error": "OpenAPI spec not found"}
