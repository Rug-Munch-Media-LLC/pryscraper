"""Pry — System router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from observability import get_metrics_output

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System"])

@router.get("/metrics", tags=["System"], summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose Prometheus metrics for scraping."""
    data, content_type = get_metrics_output()
    return Response(content=data, media_type=content_type)


@router.get(
    "/openapi.json",
    tags=["System"],
    summary="OpenAPI spec for AI agent integration",
    include_in_schema=False,
)
async def get_openapi() -> JSONResponse:
    """Get the OpenAPI specification for AI agent integration.

    Use this with ChatGPT GPT Actions, Claude MCP, or any AI agent
    framework to let AI models scrape the web through Pry.
    """
    from ai_plugin import get_openapi_spec

    spec = get_openapi_spec()
    return JSONResponse(content=spec)
