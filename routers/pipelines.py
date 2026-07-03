"""Pry — Pipelines router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pipelines"])

@router.get(
    "/v1/pipelines/steps", tags=["Pipelines"], summary="List all available pipeline step types"
)
async def list_step_types() -> dict[str, Any]:
    """List all available step types for the visual pipeline builder.

    Each step type includes: name, icon, description, required inputs with types,
    and expected outputs. A UI renders these as drag-and-drop blocks.
    """
    from pipelines import STEP_TYPES

    return {"success": True, "data": {"step_types": STEP_TYPES, "total": len(STEP_TYPES)}}


@router.post("/v1/pipelines/validate", tags=["Pipelines"], summary="Validate a pipeline definition")
async def validate_pipeline_endpoint(pipeline: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate a pipeline definition for correctness."""
    from pipelines import validate_pipeline

    errors = validate_pipeline(pipeline)
    return {"success": len(errors) == 0, "data": {"valid": len(errors) == 0, "errors": errors}}


@router.post("/v1/pipelines/run", tags=["Pipelines"], summary="Execute a pipeline")
async def run_pipeline_endpoint(
    pipeline: dict[str, Any] = Body(...),
    context: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Execute a pipeline definition.

    Steps run sequentially. Each step's output is available as
    {{step_id.output_key}} in subsequent step templates.

    Example pipeline:
    {
        "name": "Monitor Competitor Pricing",
        "steps": [
            {"id": "scrape_amazon", "type": "scrape", "inputs": {"url": "https://amazon.com/product"}},
            {"id": "extract", "type": "extract_css", "inputs": {"url": "{{scrape_amazon.url}}", "schema": {...}}},
            {"id": "quality", "type": "quality_check", "inputs": {"url": "{{scrape_amazon.url}}", "data": "{{extract.items}}"}},
            {"id": "notify", "type": "send_slack", "inputs": {"webhook_url": "https://hooks.slack.com/...", "message": "{{quality.quality_score}}"}},
        ]
    }
    """
    from pipelines import run_pipeline, validate_pipeline

    errors = validate_pipeline(pipeline)
    if errors:
        raise InvalidRequestError(f"Pipeline validation failed: {'; '.join(errors)}")
    result = await run_pipeline(pipeline, context)
    return {"success": not result["failed"], "data": result}


@router.post("/v1/pipelines/save", tags=["Pipelines"], summary="Save a pipeline definition")
async def save_pipeline_endpoint(pipeline: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Save a pipeline definition for later use."""
    from pipelines import save_pipeline

    result = save_pipeline(pipeline)
    return {"success": result["success"], "data": result}


@router.get("/v1/pipelines", tags=["Pipelines"], summary="List saved pipelines")
async def list_pipelines_endpoint() -> dict[str, Any]:
    """List all saved pipeline definitions."""
    from pipelines import list_pipelines

    pipelines = list_pipelines()
    return {"success": True, "data": {"pipelines": pipelines, "total": len(pipelines)}}


@router.get("/v1/pipelines/{pipeline_id}", tags=["Pipelines"], summary="Get a saved pipeline")
async def get_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    """Get a saved pipeline definition by ID."""
    from pipelines import get_pipeline

    result = get_pipeline(pipeline_id)
    if not result:
        raise NotFoundError(f"Pipeline not found: {pipeline_id}")
    return {"success": True, "data": result}


@router.delete("/v1/pipelines/{pipeline_id}", tags=["Pipelines"], summary="Delete a saved pipeline")
async def delete_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    """Delete a saved pipeline definition."""
    from pipelines import delete_pipeline

    success = delete_pipeline(pipeline_id)
    if not success:
        raise NotFoundError(f"Pipeline not found: {pipeline_id}")
    return {"success": True, "data": {"deleted": True}}
