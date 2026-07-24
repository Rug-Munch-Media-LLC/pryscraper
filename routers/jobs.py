"""Pry — Jobs router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from deps import queue
from errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Jobs"])

@router.get("/v1/job/{job_id}", tags=["Jobs"], summary="Get async job status and result")
async def get_job(job_id: str) -> dict[str, Any]:
    """Get async job status and result."""
    job = await queue.get_job(job_id)
    if not job:
        raise NotFoundError("Job not found")
    return {"success": True, "data": job}


@router.get("/v1/jobs", tags=["Jobs"], summary="List jobs in a Pryfile", description="List all jobs defined in a Pryfile with their current status and configuration.")
async def list_jobs(path: str = "pry.yml") -> dict[str, Any]:
    from pryfile import Pryfile

    resolved = _safe_pryfile_path(path)
    pf = Pryfile(resolved)
    return {"success": True, "data": {"jobs": pf.list_jobs()}}


def _safe_pryfile_path(path: str) -> str:
    """Resolve and validate Pryfile path — prevent directory traversal."""
    resolved = Path(path).resolve()
    allowed = Path.cwd().resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as e:
        raise InvalidRequestError(f"Path must be inside {allowed}") from e
    if not resolved.is_file():
        raise InvalidRequestError(f"File not found: {resolved}")
    return str(resolved)
