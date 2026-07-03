"""Pry — Pipeline router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from errors import InvalidRequestError
from pipeline import HOOK_POINTS, get_pipeline, run_pipeline

logger = logging.getLogger(__name__)

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


@router.post("/v1/pipeline/run", tags=["Pipeline"], summary="Run pipeline hooks for testing")
async def run_pipeline_test(
    hook_point: str = Body(...),
    url: str = Body(""),
    html: str = Body(""),
) -> dict[str, Any]:
    """Run hooks at a given pipeline point for testing."""
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
