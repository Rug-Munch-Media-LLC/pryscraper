"""Pry — Admin router: prefix, access gate, and the shared ``APIRouter``.

This is the LEAF of the admin package. Every ``admin_*`` endpoint module
imports ``router`` from here, and this module imports nothing from them —
the dependency is one-directional, so importing any endpoint module
directly (which is what the tests do) no longer trips a circular import.

``admin.py`` is the facade: it re-exports everything below for backwards
compatibility, then imports the endpoint modules so their routes are
registered on this router.

SECURITY: the prefix is read from ``PRY_ADMIN_PATH`` (or the alias
``PRY_ADMIN_PATH_SECRET``). When neither is set we fall back to a STABLE
non-secret dev default ``_DEV_ADMIN_PATH`` — the admin surface is still
loopback-only by default, and production MUST set a real secret via env
(see README / deployment). A random per-boot token is intentionally NOT
used: it made ``openapi.json`` non-deterministic, so the spec could not be
regenerated or diffed. Determinism here is a documentation/CI property;
the access gate is the loopback check, not prefix obscurity.
Admin credentials live in the deployment secrets store, not in the repo.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request

from pry.core.middleware_auth import is_loopback_client, resolve_client_ip
from pry.core.settings import settings

# ── Admin security: env-configurable prefix + loopback-only ──
# STABLE dev default (NOT a secret): keeps docs/spec generation
# deterministic when no secret is configured. Production MUST override:
#   export PRY_ADMIN_PATH=<real-secret>
# ``PRY_ADMIN_PATH_SECRET`` is accepted as an alias.
_DEV_ADMIN_PATH = "pry-admin-dev"
_ADMIN_SECRET = os.getenv("PRY_ADMIN_PATH") or os.getenv("PRY_ADMIN_PATH_SECRET") or _DEV_ADMIN_PATH
ADMIN_PREFIX = f"/{_ADMIN_SECRET}"


def _refuse_dev_prefix_in_prod() -> None:
    """Refuse to boot prod on the non-secret dev admin prefix."""
    if settings.environment == "prod" and _ADMIN_SECRET == _DEV_ADMIN_PATH:
        raise RuntimeError(
            "PRY_ADMIN_PATH must be set to a non-default secret when PRY_ENVIRONMENT=prod"
        )


_refuse_dev_prefix_in_prod()

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


def _is_loopback_host(client_host: str) -> bool:
    """True for loopback clients (including ASGI test-client hosts)."""
    return is_loopback_client(client_host) or client_host in (
        "localhost",
        "0.0.0.0",  # nosec B104 — membership check, not a bind
    )


def _require_admin_user(user_id: str) -> None:
    """Raise 403 unless *user_id* maps to a user with the ADMIN role."""
    from pry.core.db import models as _db_models
    from pry.core.db.session import get_session

    with get_session() as session:
        urow = session.query(_db_models.User).filter_by(user_id=user_id).first()
    role = str(urow.role or "") if urow is not None else ""
    if role.upper() != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access requires a user with the ADMIN role",
        )


def _require_remote_admin(request: Request) -> None:
    """Remote mode: require the caller's key to belong to an ADMIN-role user."""
    from pry.core import api_keys_service

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
    _require_admin_user(user_id)


def _check_admin_access(request: Request) -> None:
    """Enforce loopback-only admin access + admin-role RBAC in remote mode.

    Loopback (default): trusted — no key check (the outer middleware still
    applies when a global key is configured).

    Remote (``PRY_ADMIN_LOOPBACK_ONLY=false``): the presented Bearer key
    must belong to a user with ``role == "ADMIN"`` in the users table —
    ANY valid API key is NOT enough. Fail closed on every failure path.
    """
    loopback_only = _loopback_only()
    # Trusted-proxy aware: a same-host proxy makes every peer look like
    # 127.0.0.1, which used to hand the loopback bypass to the internet.
    client_host = resolve_client_ip(request.scope)
    if client_host is None:
        raise HTTPException(
            status_code=403,
            detail="Ambiguous client identity (untrusted forwarding headers)",
        )
    if _is_loopback_host(client_host) and loopback_only:
        return
    if loopback_only:
        raise HTTPException(
            status_code=403,
            detail="Admin is loopback-only. Set PRY_ADMIN_LOOPBACK_ONLY=false to expose remotely.",
        )
    _require_remote_admin(request)


router = APIRouter(prefix=ADMIN_PREFIX, tags=["Admin"], dependencies=[Depends(_check_admin_access)])
