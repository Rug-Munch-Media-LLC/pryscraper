"""Pry — credential vault read paths: per-owner get, list and delete.

Split out of ``credential_vault.py`` on the anonymous-shared-owner fix so
each module stays under the 200-line policy. Every function here is
owner-scoped and refuses the shared legacy owner ``""`` by default: that
namespace is shared by every pre-scoping caller, so serving it on the
default path is a horizontal-privilege bug (OWASP A01 / CWE-639).

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
from datetime import UTC, datetime
from typing import Any

from pry.api import credential_vault

logger = logging.getLogger(__name__)

__all__ = ["delete_credential", "get_credential", "list_credentials"]


def get_credential(credential_id: str, owner: str | None = None) -> dict[str, Any] | None:
    """Retrieve credentials from the vault (owner-scoped, secrets masked).

    When ``owner`` is provided, entries owned by a different caller are not
    returned (access control). Secrets are masked to ``***`` on read; the
    raw values remain on disk until at-rest encryption lands (see [REVIEW]).

    Raises:
        ValueError: when ``owner`` is empty. The empty owner is the shared
            legacy namespace: entries written before owner-scoping existed
            carry it, and returning them to any caller that reaches it with
            an empty owner is a horizontal-privilege bug. Callers must pass
            a real owner; an operator who genuinely needs the legacy rows
            must opt in explicitly at the router layer and say so.
    """
    if not owner:
        raise ValueError("owner is required; the shared legacy owner is not accessible by default")
    path = credential_vault._vault_path(credential_id)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text())
        if owner is not None and entry.get("owner") != owner:
            return None
        entry["last_used"] = datetime.now(UTC).isoformat()
        entry["use_count"] = entry.get("use_count", 0) + 1
        path.write_text(json.dumps(entry, indent=2))
        return credential_vault._public_entry(entry)
    except (json.JSONDecodeError, OSError):
        logger.warning("credential_vault_reads_exception_handler", exc_info=True)
        return None


def delete_credential(credential_id: str, owner: str | None = None) -> bool:
    """Delete credentials from the vault (owner-scoped).

    When ``owner`` is provided, only the owner of the entry may delete it;
    foreign entries are treated as not found. An empty ``owner`` deletes
    from the shared legacy namespace and is refused (see ``get_credential``).
    """
    if not owner:
        return False
    path = credential_vault._vault_path(credential_id)
    if not path.exists():
        return False
    if owner is not None:
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("credential_vault_reads_exception_handler", exc_info=True)
            return False
        if entry.get("owner") != owner:
            return False
    path.unlink()
    credential_vault.logger.info("credential_deleted", extra={"credential_id": credential_id})
    return True


def list_credentials(owner: str | None = None) -> list[dict[str, Any]]:
    """List stored credentials (without exposing secrets).

    When ``owner`` is provided, only entries owned by that caller are
    returned; ``None`` lists every entry (legacy behavior). Legacy entries
    stored before owner-scoping have owner ``""``.

    An empty ``owner`` string is refused: it is the shared legacy namespace,
    and listing it hands one caller every other caller's credentials. Pass
    ``None`` only from an operator path that has already decided to expose
    the whole vault.
    """
    if owner == "":
        raise ValueError("owner must be non-empty; use None to list every entry deliberately")
    credentials = []
    for path in sorted(
        credential_vault.VAULT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True
    ):
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("credential_vault_reads_exception_handler", exc_info=True)
            continue
        if owner is not None and entry.get("owner") != owner:
            continue
        credentials.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "type": entry["type"],
                "target_url": entry.get("target_url", ""),
                "created_at": entry["created_at"],
                "last_used": entry.get("last_used"),
                "use_count": entry.get("use_count", 0),
                "owner": entry.get("owner", ""),
            }
        )
    return credentials
