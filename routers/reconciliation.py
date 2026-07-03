"""Pry — Reconciliation router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reconciliation"])

@router.post(
    "/v1/reconcile",
    tags=["Reconciliation"],
    summary="Reconcile records from multiple sources into unified entities",
)
async def reconcile_endpoint(
    records: list[dict[str, Any]] = Body(...),
    vertical: str = Body("product"),
    threshold: float = Body(0.7),
) -> dict[str, Any]:
    """Reconcile records from multiple sources into matched entities.

    Matches records across sources using identity field similarity,
    normalizes to a unified vertical schema, and returns entity groups
    with confidence scores.

    Verticals: product, job, real_estate, review
    """
    from reconciliation import VERTICAL_SCHEMAS, reconcile

    if vertical not in VERTICAL_SCHEMAS:
        raise InvalidRequestError(
            f"Unknown vertical: {vertical}. Supported: {list(VERTICAL_SCHEMAS.keys())}"
        )

    result = await reconcile(records, vertical, threshold)
    return {"success": True, "data": result}


@router.get(
    "/v1/reconcile/schemas",
    tags=["Reconciliation"],
    summary="List supported reconciliation schemas",
)
async def list_schemas() -> dict[str, Any]:
    """List all supported vertical schemas for entity reconciliation."""
    from reconciliation import VERTICAL_SCHEMAS

    schemas = {}
    for key, schema in VERTICAL_SCHEMAS.items():
        schemas[key] = {
            "name": schema["name"],
            "fields": {
                k: {fk: fv for fk, fv in v.items() if fk != "type"}
                for k, v in schema["fields"].items()
            },
            "identity_fields": schema["identity_fields"],
        }

    return {"success": True, "data": {"schemas": schemas, "total": len(schemas)}}
