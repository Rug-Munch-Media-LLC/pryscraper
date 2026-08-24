"""Pry — Streams router.

Live job-progress WebSocket streams. Clients subscribe to
``/v1/stream/{job_id}`` and receive JSON broadcast events for the job
(e.g. scrape progress emitted by pryextras.streams).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pry.misc.pryextras import streams

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Streams"])


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
