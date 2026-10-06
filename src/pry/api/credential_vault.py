"""Pry — credential vault: per-owner storage with secrets masked on read.

Split out of ``auth_connector.py`` on the anonymous-shared-owner fix. The
store, read, list and delete surface is owner-scoped: every caller gets a
namespace of its own (see ``routers/core/credential_scope.py``).

The empty owner ``""`` is the SHARED LEGACY namespace — rows written before
owner-scoping existed. It is refused by default on every read path here, so
legacy shared state is inert until an operator deliberately migrates it. No
function in this module accepts an empty owner silently.

Part of Pry — Stealth / Anti-Detection Module
Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
Change Date: 2029-01-01 (converts to MIT).
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pry.core.paths import PRY_DATA_DIR
from pry.core.pathsafe import safe_join

logger = logging.getLogger(__name__)

VAULT_DIR = PRY_DATA_DIR / "vault"
VAULT_DIR.mkdir(parents=True, exist_ok=True)

#: Owner of rows written before owner-scoping existed. Shared by every
#: pre-scoping caller — the reason it is refused on every read path.
LEGACY_SHARED_OWNER = ""

#: Opt-in permitting writes into the shared legacy namespace, for a
#: deliberate operator migration. Off by default; see credential_scope.
LEGACY_STORE_OPT_IN = "PRY_ALLOW_LEGACY_SHARED_CREDENTIALS"

_TRUTHY = ("1", "true", "yes")


def _legacy_store_allowed() -> bool:
    """Return whether writing to the shared legacy namespace is opted into."""
    return os.getenv(LEGACY_STORE_OPT_IN, "").strip().lower() in _TRUTHY


# The read paths live in credential_vault_reads; re-exported here so callers
# keep a single import site. Imported last: that module imports this one.
from pry.api.credential_vault_reads import (  # noqa: E402
    delete_credential,
    get_credential,
    list_credentials,
)

__all__ = [
    "VAULT_DIR",
    "delete_credential",
    "get_credential",
    "list_credentials",
    "store_credential",
]

_MASKED = "***"


def _vault_path(credential_id: str) -> Path:
    return safe_join(VAULT_DIR, credential_id, ".json", kind="credential_id")


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a credential entry with secret values masked on read.

    The on-disk vault still holds plaintext until at-rest encryption lands
    (see [REVIEW]); every read path returns this masked shape instead.
    """
    public = dict(entry)
    public["credentials"] = _MASKED
    public["secrets_masked"] = True
    return public


def store_credential(
    name: str,
    credential_type: str,
    credentials: dict[str, Any],
    target_url: str = "",
    owner: str = "",
) -> dict[str, Any]:
    """Store credentials in the vault.

    Args:
        name: Human-readable name for this credential
        credential_type: "password", "api_key", "cookie", "token", "sso"
        credentials: Dict containing the credential details
        target_url: The URL these credentials are for
        owner: Caller identity (JWT sub / API-key hash / IP-derived anon
            owner). Credentials are scoped to this owner so other callers
            cannot read or delete them. An empty owner stores into the
            SHARED legacy namespace, which every anonymous caller could then
            reach, so it is refused unless the explicit legacy opt-in is set.

    The response masks secrets (``***``); callers never receive plaintext
    back. The on-disk entry keeps the real values for internal automation
    use until at-rest encryption is implemented (see [REVIEW]).

    Returns:
        ``{"success": False, "error": ...}`` when ``owner`` is empty and the
        legacy opt-in is not set.
    """
    if not owner and not _legacy_store_allowed():
        return {
            "success": False,
            "error": "owner is required; the shared legacy namespace is not writable by default",
        }
    credential_id = uuid.uuid4().hex[:12]
    entry = {
        "id": credential_id,
        "name": name,
        "type": credential_type,
        "target_url": target_url,
        "owner": owner,
        "credentials": credentials,
        "created_at": datetime.now(UTC).isoformat(),
        "last_used": None,
        "use_count": 0,
        "note": "WARNING: Stored as plaintext JSON on disk. API responses mask secrets; at-rest encryption is a follow-up.",
    }
    try:
        path = _vault_path(credential_id)
        path.write_text(json.dumps(entry, indent=2))
        logger.info(
            "credential_stored",
            extra={
                "credential_id": credential_id,
                "credential_name": name,
                "type": credential_type,
                "owner": owner,
            },
        )
        return {
            "success": True,
            "credential_id": credential_id,
            "credential": _public_entry(entry),
        }
    except OSError as e:
        logger.warning("credential_vault_exception_handler", exc_info=True)
        return {"success": False, "error": str(e)}
