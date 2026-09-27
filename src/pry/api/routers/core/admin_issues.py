"""Admin support-issue endpoints: outstanding issues and resolution."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from pry.api.routers.core.admin_router import router


@router.get(
    "/v1/admin/issues",
    summary="Outstanding customer issues and unresolved payments",
)
async def admin_issues() -> dict[str, Any]:
    """Support ticket summary from the in-memory issue tracker."""
    from pry.api.routers.core.admin_shared import _issue_summary

    return {"success": True, **_issue_summary()}


@router.post(
    "/v1/admin/issues/{issue_id}/resolve",
    summary="Mark a support issue as resolved",
)
async def admin_issue_resolve(issue_id: str) -> dict[str, Any]:
    """Resolve an issue by ID."""
    from pry.api.routers.core.admin_shared import _resolve_issue

    issue = _resolve_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"issue '{issue_id}' not found")
    return {"success": True, "issue": issue}
