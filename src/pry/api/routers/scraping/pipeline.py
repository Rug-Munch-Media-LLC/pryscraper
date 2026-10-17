"""Pry — Pipeline router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Response

from pry.commerce.pipeline import HOOK_POINTS, get_pipeline, run_pipeline
from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

# One release of overlap for the singular path; canonical is /v1/pipelines/run.
SUNSET_PIPELINE_RUN = "Sun, 18 Apr 2027 00:00:00 GMT"

router = APIRouter(tags=["Pipeline"])


@router.post("/v1/pipeline/hook", tags=["Pipeline"], summary="Register a hook function")
async def register_hook(
    hook_point: str = Body(...),
    javascript_fn: str = Body(...),
) -> dict[str, Any]:
    """Register a JavaScript hook function at a pipeline hook point.

    Hook points: before_scrape, after_response, before_parse, after_parse,
                 before_extract, after_extract, before_return, on_error
    """
    if hook_point not in HOOK_POINTS:
        raise InvalidRequestError(f"Unknown hook point: {hook_point}. Valid: {HOOK_POINTS}")

    # For now, just acknowledge the registration
    # In production, this would execute JS in a sandbox
    return {
        "success": True,
        "data": {
            "hook_point": hook_point,
            "registered": True,
            "message": f"Hook registered at {hook_point}. Note: custom JS hooks require a sandboxed runtime.",
        },
    }


@router.get("/v1/pipeline/hooks", tags=["Pipeline"], summary="List all registered hooks")
async def list_pipeline_hooks() -> dict[str, Any]:
    """List all registered hooks in the pipeline."""
    pipeline = get_pipeline()
    return {
        "success": True,
        "data": {
            "hooks": pipeline.list_hooks(),
            "hook_points": HOOK_POINTS,
        },
    }


@router.post(
    "/v1/pipeline/run",
    tags=["Pipeline"],
    summary="Run pipeline hooks for testing (deprecated; sunset 2027-04-18)",
    deprecated=True,
    responses={
        200: {"description": "Deprecated singular path; returns Deprecation/Sunset headers"}
    },
)
async def run_pipeline_test(
    response: Response,
    hook_point: str = Body(...),
    url: str = Body(""),
    html: str = Body(""),
) -> dict[str, Any]:
    """DEPRECATED: singular path retired in favour of the ``/v1/pipelines/*`` family.

    Removal date: **2027-04-18** (one release of overlap).

    The body (``hook_point``) is NOT the canonical pipeline-definition body, so
    this stays a behaviour-preserving alias for one release; it is deleted at
    sunset. Announced with ``Deprecation``/``Sunset`` headers.
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = SUNSET_PIPELINE_RUN
    response.headers["Link"] = '</v1/pipelines/run>; rel="successor-version"'

    if hook_point not in HOOK_POINTS:
        raise InvalidRequestError(f"Unknown hook point: {hook_point}")

    result = await run_pipeline(hook_point, url=url, html=html)
    return {
        "success": True,
        "data": {
            "hook_point": hook_point,
            "result": {k: v for k, v in result.items() if k != "html"},
            "error_count": len(result.get("errors", [])),
        },
    }
