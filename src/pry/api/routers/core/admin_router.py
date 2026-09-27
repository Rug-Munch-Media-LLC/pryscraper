"""Pry — Admin router: prefix, access gate, and the shared ``APIRouter``.

This is the LEAF of the admin package. Every ``admin_*`` endpoint module
imports ``router`` from here, and this module imports nothing from them —
the dependency is one-directional, so importing any endpoint module
directly (which is what the tests do) no longer trips a circular import.

``admin.py`` is the facade: it re-exports everything below for backwards
compatibility, then imports the endpoint modules so their routes are
registered on this router.

SECURITY: the prefix is a random 32-char hex string generated on every
boot unless ``PRY_ADMIN_PATH`` is set, so the surface is undiscoverable
without reading container logs. Access is loopback-only by default.
Admin credentials live in the deployment secrets store, not in the repo.
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

# ── Admin security: random prefix + loopback-only ──
# Random 32-char hex prevents discovery. Override with PRY_ADMIN_PATH.
_ADMIN_SECRET = os.getenv("PRY_ADMIN_PATH", "") or secrets.token_hex(16)
ADMIN_PREFIX = f"/{_ADMIN_SECRET}"

# Loopback-only: returns 403 for non-local clients even with valid API key.
ADMIN_LOOPBACK_ONLY = os.getenv("PRY_ADMIN_LOOPBACK_ONLY", "true").lower() in ("true", "1", "yes")


def _loopback_only() -> bool:
    """Read the loopback flag through the ``admin`` facade at CALL time.

    ``ADMIN_LOOPBACK_ONLY`` is re-exported by ``admin.py``, so the tests and
    operators toggle it there — a plain ``from … import`` re-export would copy
    the value and the switch would go dead. This is the same deferred-module
    read ``admin_shared._data_dir()`` uses for ``PRY_DATA_DIR``; the import is
    function-local, so the package graph stays acyclic at import time.
    """
    from pry.api.routers.core import admin as _admin

    return bool(_admin.ADMIN_LOOPBACK_ONLY)


def _check_admin_access(request: Request) -> None:
    """Enforce loopback-only admin access + admin-role RBAC in remote mode.

    Loopback (default): trusted — no key check (the outer middleware still
    applies when a global key is configured).

    Remote (``PRY_ADMIN_LOOPBACK_ONLY=false``): the presented Bearer key
    must belong to a user with ``role == "ADMIN"`` in the users table —
    ANY valid API key is NOT enough. Fail closed on every failure path.
    """
    loopback_only = _loopback_only()
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "0.0.0.0")  # nosec B104 — loopback membership check, not a bind
    if is_loopback and loopback_only:
        return
    if loopback_only:
        raise HTTPException(
            status_code=403,
            detail="Admin is loopback-only. Set PRY_ADMIN_LOOPBACK_ONLY=false to expose remotely.",
        )
    # Remote mode: require the caller's key to belong to an ADMIN-role user.
    from pry.core import api_keys_service
    from pry.core.db.session import get_session

    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not bearer:
        raise HTTPException(status_code=403, detail="Admin (remote) requires an API key")
    record = api_keys_service.authenticate(bearer)
    if record is None:
        raise HTTPException(status_code=403, detail="Invalid API key for admin access")
    user_id = str(record.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=403, detail="Key is not bound to a user")
    from pry.core.db import models as _db_models

    with get_session() as session:
        urow = session.query(_db_models.User).filter_by(user_id=user_id).first()
    if urow is None or str(urow.role or "").upper() != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access requires a user with the ADMIN role",
        )


router = APIRouter(prefix=ADMIN_PREFIX, tags=["Admin"], dependencies=[Depends(_check_admin_access)])
