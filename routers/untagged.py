"""Pry — Untagged router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pryextras import streams

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Untagged"])


@router.websocket("/v1/stream/{job_id}")
async def stream_endpoint(websocket: WebSocket, job_id: str = "live") -> None:
    await websocket.accept()
    streams.register(job_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await streams.broadcast(job_id, {"echo": data})
    except WebSocketDisconnect:
        streams.unregister(job_id, websocket)
