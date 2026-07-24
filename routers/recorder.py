"""Pry — Recorder router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pryextras import recorder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Recorder"])

@router.post("/v1/record/start", tags=["Recorder"], summary="Start recording browser actions", description="Start recording a sequence of browser actions for later replay or export.")
async def start_recording(session_id: str = Body(...)) -> dict[str, Any]:
    recorder.start(session_id)
    return {"success": True, "data": {"session_id": session_id, "status": "recording"}}


@router.post("/v1/record/step", tags=["Recorder"], summary="Record a browser action step", description="Record a single browser action step (click, type, navigate) as part of an active recording session.")
async def record_step(
    session_id: str = Body(...), action: str = Body(...), selector: str = "", value: str = ""
) -> dict[str, Any]:
    recorder.record(session_id, action, selector, value)
    return {"success": True, "data": {"recorded": len(recorder._recordings.get(session_id, []))}}


@router.post("/v1/record/export", tags=["Recorder"], summary="Export recording as script", description="Export a browser recording session as a reusable Playwright script.")
async def export_recording(session_id: str = Body(...), fmt: str = "json") -> dict[str, Any]:
    script = recorder.export(session_id, fmt)
    return {"success": True, "data": {"script": script, "format": fmt}}


@router.post("/v1/record/clear", tags=["Recorder"], summary="Clear recorded actions", description="Clear all recorded browser actions from the current session.")
async def clear_recording(session_id: str = Body(...)) -> dict[str, Any]:
    recorder.clear(session_id)
    return {"success": True, "data": {"status": "cleared"}}
