"""Pry — Sessions router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body

from deps import automator
from errors import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sessions"])

@router.post("/v1/session/create", tags=["Sessions"], summary="Create a persistent browser session")
async def create_session(url: str = Body(...), persist: bool = True) -> dict[str, Any]:
    """Create a persistent browser session."""
    session_id = await automator.create_session(url, persist=persist)

    if persist:
        from sessions import save_session

        await save_session(
            session_id=session_id,
            cookies=[],
            metadata={"url": url, "created_at": datetime.now(UTC).isoformat()},
        )

    return {"success": True, "data": {"session_id": session_id, "persist": persist}}


@router.post(
    "/v1/session/destroy", tags=["Sessions"], summary="Destroy a browser session with optional save"
)
async def destroy_session(
    session_id: str = Body(...),
    save_state: bool = Body(False),
) -> dict[str, Any]:
    """Destroy a browser session. Optionally save state first."""
    from sessions import delete_session, save_session

    if save_state:
        state = await automator.get_session_state(session_id)
        if state:
            await save_session(
                session_id=session_id,
                cookies=state.get("cookies", []),
                local_storage=state.get("local_storage", {}),
                metadata={"destroyed_at": datetime.now(UTC).isoformat()},
            )

    success = await automator.destroy_session(session_id)
    if not save_state:
        await delete_session(session_id)

    return {"success": True, "data": {"session_id": session_id, "destroyed": success}}


@router.get("/v1/sessions", tags=["Sessions"], summary="List all persistent sessions")
async def list_sessions() -> dict[str, Any]:
    """List all persistent sessions (active + saved)."""
    from sessions import list_sessions as list_saved_sessions

    active = automator.list_sessions()
    saved = await list_saved_sessions()

    return {
        "success": True,
        "data": {
            "active": active,
            "saved": saved,
            "total_active": len(active),
            "total_saved": len(saved),
        },
    }


@router.post("/v1/session/save", tags=["Sessions"], summary="Save current session state to disk")
async def save_session_state(
    session_id: str = Body(...),
) -> dict[str, Any]:
    """Save a session's current state (cookies, storage) to disk."""
    from sessions import save_session as save_session_to_disk

    state = await automator.get_session_state(session_id)
    if not state:
        raise NotFoundError(f"Session not found: {session_id}")

    await save_session_to_disk(
        session_id=session_id,
        cookies=state.get("cookies", []),
        local_storage=state.get("local_storage", {}),
        session_storage=state.get("session_storage", {}),
        metadata={"source": "manual_save"},
    )

    return {
        "success": True,
        "data": {"session_id": session_id, "cookie_count": len(state.get("cookies", []))},
    }


@router.post("/v1/session/restore", tags=["Sessions"], summary="Restore a saved session")
async def restore_session(session_id: str = Body(...)) -> dict[str, Any]:
    """Restore a session from disk into a browser context."""
    from sessions import load_session

    data = await load_session(session_id)
    if not data:
        raise NotFoundError(f"Saved session not found: {session_id}")

    success = await automator.restore_session_state(
        session_id=session_id,
        cookies=data.get("cookies", []),
    )

    return {
        "success": success,
        "data": {
            "session_id": session_id,
            "restored": success,
            "cookie_count": len(data.get("cookies", [])),
            "saved_at": data.get("saved_at", ""),
        },
    }
