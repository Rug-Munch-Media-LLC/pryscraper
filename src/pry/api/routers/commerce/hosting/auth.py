"""Authentication and ownership checks for hosted-instance routes."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from fastapi import HTTPException

from pry.commerce.hosting import InstanceNotFound, get_instance, list_instances


def _resolve_user(bearer: str) -> str:
    """Resolve a Bearer API key to its owner user_id (401 on failure)."""
    from pry.core.api_keys_service import authenticate

    record = authenticate(bearer.strip())
    if record is None:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return str(record["user_id"])


def _require_owner(instance_id: str, user_id: str) -> None:
    """Raise 404 unless *instance_id* exists and belongs to *user_id*."""
    owned = {item["instance_id"] for item in list_instances(user_id)}
    if instance_id not in owned:
        try:
            get_instance(instance_id)
        except InstanceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=404, detail="unknown hosted instance")
