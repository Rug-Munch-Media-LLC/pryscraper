# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Legacy-namespace tests for the credential vault.

The shared legacy owner ``""`` holds rows written before owner-scoping
existed. It must stay inert and intact: gated rather than silently served,
never silently rewritten, never deleted. These tests use the shared
``isolated_vault`` fixture (tests/conftest.py) so nothing here reads or
writes the operator's real ``~/.pry/vault``.

Cross-caller isolation lives in tests/test_authz_credential_scope.py.
"""

from __future__ import annotations

import importlib
import inspect
import json
from typing import Any

import pytest

from pry.api import credential_vault
from pry.api.routers.core import credential_scope
from pry.core.errors import InvalidRequestError
from tests.authz_support import isolated_vault, set_env  # noqa: F401


def _write_legacy_row(vault: Any, credential_id: str) -> None:
    """Write a pre-scoping row into the shared legacy namespace."""
    (vault / f"{credential_id}.json").write_text(
        json.dumps(
            {
                "id": credential_id,
                "name": "old",
                "type": "password",
                "target_url": "",
                "owner": "",
                "credentials": {"password": "old"},
                "created_at": "2020-01-01T00:00:00+00:00",
                "last_used": None,
                "use_count": 0,
            }
        )
    )


def _anon_request(ip: str = "198.51.100.10") -> Any:
    """An unauthenticated request shape as _request_owner sees it."""
    from unittest.mock import MagicMock

    req = MagicMock(spec=["state", "headers", "scope"])
    req.state.identity = None
    req.state.user_id = None
    req.headers = {}
    req.scope = {"client": (ip, 5555), "headers": []}
    return req


def test_legacy_owner_count_is_read_only(isolated_vault: Any) -> None:
    """The legacy-count helper reports without mutating anything.

    Kills: a "count" helper that also rewrites or prunes rows while counting.
    """
    for i in range(3):
        _write_legacy_row(isolated_vault, f"leg{i}")
    (isolated_vault / "owned.json").write_text(
        json.dumps({"id": "owned", "owner": "anon:abc", "name": "n", "type": "password"})
    )
    before = {p.name: p.read_text() for p in isolated_vault.glob("*.json")}

    assert credential_scope.legacy_owner_count(isolated_vault) == 3

    assert {p.name: p.read_text() for p in isolated_vault.glob("*.json")} == before


def test_legacy_opt_in_makes_legacy_namespace_writable(isolated_vault: Any, set_env) -> None:
    """An operator opt-in permits writing to "" without destroying old rows.

    Kills: removing the opt-in write path, which would leave an operator with
    no supported way to claim legacy rows, and any change that "claims" them
    by overwriting rather than by the caller writing their own row.
    """
    _write_legacy_row(isolated_vault, "legacy000001")
    before = (isolated_vault / "legacy000001.json").read_text()

    set_env({credential_vault.LEGACY_STORE_OPT_IN: "1"})
    written = credential_vault.store_credential(
        name="claimed", credential_type="token", credentials={"t": "v"}, owner=""
    )

    assert written["success"] is True
    # The pre-existing legacy row is intact — additive, not a rewrite.
    assert (isolated_vault / "legacy000001.json").read_text() == before
    # And the new row really is in the shared namespace it claimed.
    stored = json.loads((isolated_vault / f"{written['credential_id']}.json").read_text())
    assert stored["owner"] == credential_scope.LEGACY_SHARED_OWNER


def test_restart_does_not_widen_visibility(isolated_vault: Any) -> None:
    """Re-importing the vault module keeps owner scoping intact.

    Kills: any in-memory owner cache that would make a restart widen
    visibility — the owner lives in the persisted row, not in a singleton.
    """
    cred_id = "persisted01"
    (isolated_vault / f"{cred_id}.json").write_text(
        json.dumps(
            {
                "id": cred_id,
                "name": "persisted",
                "type": "password",
                "owner": "anon:aaa",
                "credentials": {"p": "x"},
                "created_at": "2020-01-01T00:00:00+00:00",
            }
        )
    )

    reloaded = importlib.reload(credential_vault)
    try:
        reloaded.VAULT_DIR = isolated_vault
        assert reloaded.get_credential(cred_id, owner="anon:bbb") is None
        own = reloaded.get_credential(cred_id, owner="anon:aaa")
        assert own is not None
        assert own["id"] == cred_id
        assert [c["id"] for c in reloaded.list_credentials(owner="anon:bbb")] == []
    finally:
        reloaded.VAULT_DIR = isolated_vault


def test_store_refusal_leaves_no_row(isolated_vault: Any) -> None:
    """Refusing an owner-less store must not leave a partial file behind.

    Kills: a store path that writes the file and then returns the refusal.
    """
    result = credential_vault.store_credential(
        name="No Owner", credential_type="token", credentials={"t": "v"}
    )

    assert result["success"] is False
    assert list(isolated_vault.glob("*.json")) == []


def test_shared_namespace_is_never_a_read_default() -> None:
    """The read paths must never default their owner to the shared "".

    Kills: reintroducing ``owner: str = ""`` as a default, which is how
    every anonymous caller ended up sharing one credential namespace.
    """
    for func in (credential_vault.get_credential, credential_vault.delete_credential):
        defaults = func.__defaults__ or ()
        assert all(default != "" for default in defaults), (
            f"{func.__name__} defaults to shared owner"
        )


def test_shared_namespace_is_never_a_write_default() -> None:
    """A store with no owner must be refused, not silently pooled.

    Kills: dropping the empty-owner refusal so anonymous stores land in the
    shared legacy namespace again.
    """
    # The signature keeps "" for backward compatibility, so assert on
    # behaviour rather than introspection: the refusal must stand.
    assert inspect.signature(credential_vault.store_credential) is not None
    assert (
        credential_vault.store_credential(
            name="pooled", credential_type="token", credentials={"t": "v"}
        )["success"]
        is False
    )


def test_request_owner_legacy_shared_requires_opt_in(set_env):
    """An unresolvable client IP must not silently become the shared owner."""
    set_env({credential_scope.ALLOW_LEGACY_SHARED_OWNER: ""})
    with pytest.raises(InvalidRequestError):
        credential_scope.request_owner(_anon_request(""))
    set_env({credential_scope.ALLOW_LEGACY_SHARED_OWNER: "1"})
    assert credential_scope.request_owner(_anon_request("")) == credential_scope.LEGACY_SHARED_OWNER


def test_request_owner_require_auth_flag_refuses_anonymous(set_env):
    set_env({credential_scope.REQUIRE_AUTH_FOR_CREDENTIALS: "1"})
    with pytest.raises(InvalidRequestError):
        credential_scope.request_owner(_anon_request())
