"""Pry — Jobs router.

Hosts the original async-job-status routes (auto-extracted from api.py
during the router-split refactor) plus the jobs-data endpoints backed by
the ``jobs`` subpackage (``ats`` + ``salary``), which is built in
parallel by other agents — every import is guarded and degrades to 502
while a module has not landed yet.

Endpoints:
- GET /v1/job/{job_id}                 — async job status and result
- GET /v1/jobs                         — list jobs in a Pryfile
- GET /v1/jobs/{board}/{company}       — ATS job listings (greenhouse/lever/ashby/workday)
- GET /v1/jobs/search                  — cross-board keyword search
- GET /v1/jobs/{board}/job/{id}        — one ATS job's full detail
- GET /v1/jobs/salary/{company}        — Levels.fyi salary bands
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from pry.core.deps import queue
from pry.core.errors import ExternalServiceError, InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Jobs"])


# ── Original api.py routes (async job status / Pryfile jobs) ──────────
@router.get("/v1/job/{job_id}", tags=["Jobs"], summary="Get async job status and result")
async def get_job(job_id: str) -> dict[str, Any]:
    """Get async job status and result."""
    job = await queue.get_job(job_id)
    if not job:
        raise NotFoundError("Job not found")
    return {"success": True, "data": job}


@router.get(
    "/v1/jobs",
    tags=["Jobs"],
    summary="List jobs in a Pryfile",
    description="List all jobs defined in a Pryfile with their current status and configuration.",
)
async def list_jobs(path: str = "pry.yml") -> dict[str, Any]:
    from pry.misc.pryfile import Pryfile

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


# ── jobs subpackage (parallel build) ───────────────────────────────────
def _jobs_module(module_name: str) -> Any:
    """Import a ``jobs`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.jobs.{module_name}")
    except ImportError:
        # NOTE: ``extra`` must not use stdlib LogRecord-reserved keys (e.g.
        # "module"), which raise KeyError on plain stdlib loggers.
        logger.warning("jobs_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"jobs.{module_name} is not available yet (parallel build in progress)"
    )


# NOTE: static-segment routes MUST be registered before the parametrized
# ``/v1/jobs/{board}/{company}`` route — Starlette returns the first FULL
# match, so ``/v1/jobs/salary/{company}`` would otherwise be swallowed by
# ``{board}/{company}`` (board="salary").


@router.get(
    "/v1/jobs/search",
    tags=["Jobs"],
    summary="Cross-board job search",
)
async def jobs_search(
    q: str = Query(..., min_length=1, description="Keyword to match in title or location"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search known ATS boards for jobs matching a keyword."""
    mod = _jobs_module("ats")
    if mod is None:
        _module_unavailable("ats")
    data = await mod.search_jobs(q, limit=limit)
    return {"success": True, "data": data}


@router.get(
    "/v1/jobs/salary/{company}",
    tags=["Jobs"],
    summary="Salary bands for a company/role from Levels.fyi",
)
async def jobs_salary(
    company: str,
    role: str = Query(
        "software_engineer", description="Role slug (e.g. 'software_engineer', 'product_manager')"
    ),
) -> dict[str, Any]:
    """Return per-level salary bands (total comp, base, stock, bonus)."""
    mod = _jobs_module("salary")
    if mod is None:
        _module_unavailable("salary")
    data = await mod.get_salary(company, role=role)
    return {"success": bool(data), "data": data}


@router.get(
    "/v1/jobs/{board}/{company}",
    tags=["Jobs"],
    summary="List job postings from an ATS board",
)
async def jobs_list(
    board: str,
    company: str,
    limit: int = Query(50, ge=1, le=500, description="Max listings (default: 50)"),
) -> dict[str, Any]:
    """Return normalized ATS job listings for a company."""
    mod = _jobs_module("ats")
    if mod is None:
        _module_unavailable("ats")
    data = await mod.list_jobs(company, board=board, limit=limit)
    return {"success": True, "data": data, "board": board, "company": company}


@router.get(
    "/v1/jobs/{board}/job/{job_id}",
    tags=["Jobs"],
    summary="Get one job's full detail from an ATS board",
)
async def jobs_get(
    board: str,
    job_id: str,
    company: str = Query(..., description="Company slug on the board (e.g. 'stripe')"),
) -> dict[str, Any]:
    """Return the full detail (description/requirements/compensation) for one job."""
    mod = _jobs_module("ats")
    if mod is None:
        _module_unavailable("ats")
    data = await mod.get_job(job_id, board=board, company=company)
    return {"success": bool(data), "data": data}
