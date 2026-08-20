"""Pry — Automation router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

import pydantic
from fastapi import APIRouter, Body
from pydantic import BaseModel

from deps import automator
from errors import ExternalServiceError, PryError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Automation"])


@router.post("/v1/automate", tags=["Automation"], summary="Execute browser automation steps")
async def automate(request: AutomateRequest) -> dict[str, Any]:
    """Execute browser automation steps. Sessions persist for login flows."""
    try:
        steps = [s.model_dump() for s in request.steps]
        result = await automator.run_steps(
            steps=steps,
            session_id=request.session_id,
            headless=True if request.headless is None else request.headless,
            viewport=request.viewport,
        )
        return {"success": True, "data": result}
    except PryError:
        raise
    except pydantic.ValidationError as e:
        raise ExternalServiceError(str(e)) from e


@router.post("/v1/screenshot", tags=["Automation"], summary="Take a screenshot of a URL")
async def screenshot(
    url: str = Body(..., embed=True), session_id: str | None = None
) -> dict[str, Any]:
    """Take a screenshot of a URL. Returns base64 PNG."""
    try:
        result = await automator.run_steps(
            steps=[{"action": "navigate", "url": url}, {"action": "screenshot"}],
            session_id=session_id,
        )
        screenshot_data = None
        for step in result.get("steps", []):
            if step.get("action") == "screenshot":
                screenshot_data = step.get("screenshot")
        return {"success": True, "data": {"screenshot": screenshot_data or ""}}
    except PryError:
        raise
    except pydantic.ValidationError as e:
        raise ExternalServiceError(str(e)) from e


class AutomateRequest(BaseModel):
    session_id: str | None = None
    steps: list[AutomateStep]
    headless: bool | None = True
    viewport: dict[str, int] | None = None


class AutomateStep(BaseModel):
    action: str
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    timeout: int | None = 30000
    wait_until: str | None = "networkidle"
