"""Pry — Batch router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from pryextras import BatchProcessor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Batch"])


@router.post(
    "/v1/batch-file", tags=["Batch"], summary="Batch scrape URLs from a file with templates"
)
async def batch_from_file(request: BatchFileRequest) -> dict[str, Any]:
    bp = BatchProcessor()
    results = await bp.from_file(
        request.filepath, request.template, request.timeout or 30, request.max_urls or 1000
    )
    return {"success": True, "data": {"total": len(results), "results": results}}


class BatchFileRequest(BaseModel):
    filepath: str
    template: dict[str, str]
    timeout: int | None = 30
    max_urls: int | None = 1000
