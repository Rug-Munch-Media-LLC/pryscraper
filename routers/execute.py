"""Pry — Execute router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from deps import scraper
from errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Execute"])

@router.post("/v1/run", tags=["Execute"], summary="Execute a Pryfile")
async def run_pryfile(path: str = Body("pry.yml")) -> dict[str, Any]:
    from pryfile import Pryfile

    resolved = _safe_pryfile_path(path)
    pf = Pryfile(resolved)
    results = await pf.run_all(scraper)
    return {"success": True, "data": {"jobs": results, "total": len(results)}}


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
