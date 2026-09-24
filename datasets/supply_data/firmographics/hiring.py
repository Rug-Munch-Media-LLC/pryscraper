"""Public job-board hiring signal for firmographics."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

import httpx

from datasets.supply_data.firmographics.http import _HEADERS, _TIMEOUT

logger = logging.getLogger(__name__)
_JOB_BOARDS: tuple[tuple[str, str], ...] = (
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"),
)


async def _board_jobs(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    """Fetch one job board's postings; return raw jobs or ``[]``."""
    try:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.debug("firmographics_job_board_fetch_failed", exc_info=True, extra={"url": url})
        return []
    if isinstance(payload, list):
        return [job for job in payload if isinstance(job, dict)]
    if isinstance(payload, dict):
        for key in ("jobs", "postings", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [job for job in value if isinstance(job, dict)]
    return []


async def _count_hiring_openings(slug: str) -> int:
    """Count jobs from the first public board that returns postings."""
    total = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            for board, template in _JOB_BOARDS:
                jobs = await _board_jobs(client, template.format(slug=slug))
                if jobs:
                    total += len(jobs)
                    logger.info(
                        "firmographics_job_board_hit",
                        extra={"board": board, "openings": len(jobs)},
                    )
                    break
    except (httpx.HTTPError, OSError):
        logger.debug("firmographics_job_board_client_failed", exc_info=True)
    return total
