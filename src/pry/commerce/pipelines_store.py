"""Pry — Pipeline persistence (CRUD).

Save/load/list/delete pipeline definitions as JSON files."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

PIPELINE_DIR = PRY_DATA_DIR / "pipelines"
PIPELINE_DIR.mkdir(parents=True, exist_ok=True)


def save_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Save a pipeline definition."""
    pipeline_id = pipeline.get("id") or uuid.uuid4().hex[:8]
    pipeline["id"] = pipeline_id
    pipeline["updated_at"] = datetime.now(UTC).isoformat()
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    try:
        path.write_text(json.dumps(pipeline, indent=2))
        logger.info(
            "pipeline_saved",
            extra={"pipeline_id": pipeline_id, "pipeline_name": pipeline.get("name")},
        )
        return {"success": True, "pipeline_id": pipeline_id}
    except OSError as e:
        return {"success": False, "error": str(e)}


def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    """Get a saved pipeline definition."""
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def list_pipelines() -> list[dict[str, Any]]:
    """List all saved pipelines."""
    pipelines = []
    for path in sorted(PIPELINE_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            pipelines.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name", "Unnamed"),
                    "description": data.get("description", ""),
                    "step_count": len(data.get("steps", [])),
                    "updated_at": data.get("updated_at"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return pipelines


def delete_pipeline(pipeline_id: str) -> bool:
    """Delete a saved pipeline."""
    path = PIPELINE_DIR / f"{pipeline_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
