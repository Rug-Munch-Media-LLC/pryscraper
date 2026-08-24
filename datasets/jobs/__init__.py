"""Pry — jobs & salary intelligence package.

Job listings from the major applicant-tracking systems that expose free,
no-auth JSON boards (Greenhouse, Lever, Ashby, Workday), plus salary-band
data scraped from Levels.fyi's embedded ``__NEXT_DATA__`` JSON.

Public API (all functions are ``async`` and *never raise* — they return
``[]`` / ``{}`` on any failure):

====================  ===========================================
``ats.list_jobs(company, board, limit)``  → list[dict]  (id, title,
                                      company, location, remote,
                                      url, posted_at)
``ats.search_jobs(query, limit)``   → list[dict]  (cross-board search)
``ats.get_job(job_id, board, company)``   → dict  (detail schema)
``salary.get_salary(company, role)``      → dict  (levels + samples)
====================  ===========================================

For convenience this package re-exports the public functions so callers
can ``from jobs import list_jobs, get_salary``::

    from jobs import list_jobs, search_jobs, get_job, get_salary

    jobs = await list_jobs("stripe", board="greenhouse", limit=10)
    band = await get_salary("google")

Contracts:

* **Never raise.** Every public function catches provider/transport/parse
  failures and returns ``{}`` (single item) or ``[]`` (lists) instead.
* **No secrets.** All endpoints are public, keyless, and free-tier. No
  credentials are read or required.
* **Cached.** A tiny in-memory TTL cache (5 minutes) avoids hammering the
  free boards on repeat calls.

Submodules stay importable so consumers can use the per-provider names
directly: ``from jobs.ats import list_jobs``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from .ats import get_job, list_jobs, search_jobs
from .salary import get_salary

__version__ = "1.0.0"

__all__ = ["get_job", "get_salary", "list_jobs", "search_jobs"]
