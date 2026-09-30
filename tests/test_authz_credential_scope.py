# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Authorization tests for the credential vault — the first `authz` suite.

Covers OWASP A01 Broken Access Control / CWE-639 (IDOR) on
``/v1/auth/credentials``: two callers must not see, read or delete each
other's credentials, and the shared legacy ``""`` namespace must not be
reachable by default.

Every test names the mutation it kills. A test that survives reverting the
per-caller owner derivation is decoration and does not belong here.

Vault isolation: ``isolated_vault`` points the vault module at ``tmp_path``
and restores the original directory afterwards, so this suite never reads or
writes the operator's real ``~/.pry/vault``.
"""

from __future__ import annotations

from tests.authz_support import isolated_vault, set_env  # noqa: F401

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api import credential_vault
from pry.api.exception_handlers import add_error_handlers
from pry.api.routers.core import credential_scope
from pry.api.routers.core.auth import router

if TYPE_CHECKING:
    from pathlib import Path

app = FastAPI()
# Production maps PryError subclasses to their status_code; the bare test app
# must do the same or a 400/404 surfaces as a 500 and the test proves nothing.
add_error_handlers(app)
app.include_router(router)

# Two distinct unauthenticated callers. "testclient" is a loopback alias, so
# the trusted-proxy resolver passes X-Forwarded-For through for these peers.
CALLER_A_IP = "198.51.100.10"
CALLER_B_IP = "198.51.100.11"


def _request(ip: str) -> MagicMock:
    """The raw ASGI-ish request shape _request_owner sees for `ip`."""
    req = MagicMock(spec=["state", "headers", "scope"])
    req.state.identity = None
    req.state.user_id = None
    req.headers = {}
    req.scope = {"client": ("testclient", 50000), "headers": [(b"x-forwarded-for", ip.encode())]}
    return req


def _client(ip: str) -> TestClient:
    """A TestClient whose requests appear to arrive from `ip`."""
    return TestClient(
        app,
        raise_server_exceptions=False,
        client=("testclient", 50000),
        headers={"x-forwarded-for": ip},
    )


def _store(client: TestClient, name: str) -> str:
    resp = client.post(
        "/v1/auth/credentials",
        json={
            "name": name,
            "credential_type": "password",
            "credentials": {"username": "admin", "password": "hunter2"},
            "target_url": "https://example.com/login",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["credential"]["id"])


def test_anonymous_caller_cannot_list_another_callers_credentials(isolated_vault: Path) -> None:
    """Caller B's list must not contain caller A's credential.

    Kills: reverting the owner derivation to the shared "" sentinel.
    """
    cred_id = _store(_client(CALLER_A_IP), "caller-a-secret")

    body = _client(CALLER_B_IP).get("/v1/auth/credentials").json()

    assert body["data"]["total"] == 0
    assert cred_id not in [c["id"] for c in body["data"]["credentials"]]


def test_anonymous_caller_cannot_read_another_callers_credential(isolated_vault: Path) -> None:
    """A foreign read at the store layer returns nothing, not the entry.

    Kills: dropping the owner equality check in get_credential, or passing
    owner=None from a router path.
    """
    cred_id = _store(_client(CALLER_A_IP), "caller-a-secret")

    assert credential_vault.get_credential(cred_id, owner="anon:someone-else") is None

    # The legitimate owner reads their own entry back, with secrets masked.
    owner_a = _client(CALLER_A_IP).get("/v1/auth/credentials").json()["data"]
    assert owner_a["credentials"][0]["owner"] == credential_scope.request_owner(
        _request(CALLER_A_IP)
    )
    assert credential_vault.get_credential(
        cred_id, owner=owner_a["credentials"][0]["owner"]
    )["credentials"] == "***"


def test_anonymous_caller_cannot_delete_another_callers_credential(isolated_vault: Path) -> None:
    """Caller B's DELETE must 404 and leave caller A's credential on disk.

    Kills: removing the owner check in delete_credential, and the router
    passing a shared owner so every anonymous delete succeeded.
    """
    cred_id = _store(_client(CALLER_A_IP), "caller-a-secret")

    resp = _client(CALLER_B_IP).delete(f"/v1/auth/credentials/{cred_id}")

    assert resp.status_code == 404
    assert (isolated_vault / f"{cred_id}.json").exists()
    # Caller A still owns it and can still delete it.
    assert _client(CALLER_A_IP).delete(f"/v1/auth/credentials/{cred_id}").status_code == 200


def test_authenticated_caller_keeps_working(isolated_vault: Path) -> None:
    """An API-key caller stores, lists and deletes under its own owner.

    Kills: an over-tight fix that refuses every caller, or that changes the
    key: owner prefix and orphans existing authenticated credentials.
    """
    authed = _client(CALLER_A_IP)
    authed.headers["authorization"] = "Bearer pry-testkey-abc"

    cred_id = _store(authed, "authed-secret")
    listed = authed.get("/v1/auth/credentials").json()["data"]

    assert listed["total"] == 1
    assert listed["credentials"][0]["owner"].startswith("key:")
    assert authed.delete(f"/v1/auth/credentials/{cred_id}").status_code == 200


def test_legacy_empty_owner_is_gated_by_default(isolated_vault: Path, set_env) -> None:
    """Legacy "" rows exist but are not readable or writable by default.

    Kills: any change that makes "" reachable without the opt-in flag —
    the read paths raising ValueError, and the write path refusing.
    """
    legacy_id = "legacy000001"
    (isolated_vault / f"{legacy_id}.json").write_text(
        '{"id": "legacy000001", "name": "old", "type": "password",'
        ' "target_url": "", "owner": "", "credentials": {"password": "old"},'
        ' "created_at": "2020-01-01T00:00:00+00:00", "last_used": null,'
        ' "use_count": 0}'
    )

    with pytest.raises(ValueError, match="owner is required"):
        credential_vault.get_credential(legacy_id, owner="")
    with pytest.raises(ValueError, match="owner must be non-empty"):
        credential_vault.list_credentials(owner="")
    assert credential_vault.delete_credential(legacy_id, owner="") is False

    # The row is untouched: gated, not migrated or destroyed.
    assert (isolated_vault / f"{legacy_id}.json").exists()

    # An operator opt-in makes the row writable, still without deleting it.
    set_env({credential_vault.LEGACY_STORE_OPT_IN: "1"})
    written = credential_vault.store_credential(
        name="claimed", credential_type="token", credentials={"t": "v"}, owner=""
    )
    assert written["success"] is True
    assert (isolated_vault / f"{legacy_id}.json").exists()


def test_anonymous_caller_is_ip_scoped_not_shared() -> None:
    """An unauthenticated caller gets its own namespace, never the shared "".

    Kills M1: ``request_owner`` returning the legacy shared owner for an
    anonymous request instead of a per-caller namespace.
    """
    owner = credential_scope.request_owner(_request("203.0.113.9"))
    assert owner.startswith("anon:")
    assert owner != credential_scope.LEGACY_SHARED_OWNER
    # Stable for the same caller across requests.
    assert credential_scope.request_owner(_request("203.0.113.9")) == owner
    # And two anonymous callers never land in the same namespace.
    other = credential_scope.request_owner(_request("198.51.100.7"))
    assert other != owner
