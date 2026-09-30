# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for enterprise SSO / auth connector.

The vault half of this file used to call ``store_credential()`` with no
``tmp_path`` isolation, so it read and wrote the operator's LIVE
``~/.pry/vault`` (2500+ real credential rows on Talos) and — because it
passed no ``owner`` — wrote into the shared legacy namespace. Every vault
test here now takes the ``isolated_vault`` fixture, which repoints the vault
module at a tmp_path and restores it afterwards. The owner-scoping rules are
asserted in tests/test_authz_credential_scope.py.
"""

from pathlib import Path

from pry.api.auth_connector import (
    SSO_PROVIDERS,
    delete_credential,
    list_credentials,
    store_credential,
)
from tests.authz_support import isolated_vault  # noqa: F401

OWNER = "test-owner-isolated"


def test_sso_providers() -> None:
    assert "okta" in SSO_PROVIDERS
    assert "azure_ad" in SSO_PROVIDERS
    assert "google_workspace" in SSO_PROVIDERS
    assert "onelogin" in SSO_PROVIDERS


def test_store_credential(isolated_vault: Path) -> None:
    result = store_credential(
        name="Test Login",
        credential_type="password",
        credentials={"username": "admin", "password": "secret123"},
        target_url="https://example.com/login",
        owner=OWNER,
    )
    assert result["success"] is True
    assert "credential_id" in result
    assert result["credential"]["name"] == "Test Login"


def test_store_and_list(isolated_vault: Path) -> None:
    store_credential(
        name="List Test",
        credential_type="api_key",
        credentials={"key": "abc123"},
        owner=OWNER,
    )
    creds = list_credentials(owner=OWNER)
    names = [c["name"] for c in creds]
    assert "List Test" in names


def test_store_and_delete(isolated_vault: Path) -> None:
    result = store_credential(
        name="Delete Test",
        credential_type="password",
        credentials={"user": "test"},
        owner=OWNER,
    )
    cred_id = result["credential"]["id"]
    assert delete_credential(cred_id, owner=OWNER) is True
    assert delete_credential(cred_id, owner=OWNER) is False


def test_list_no_secrets(isolated_vault: Path) -> None:
    store_credential(
        name="Secret Test",
        credential_type="password",
        credentials={"password": "super-secret-value"},
        owner=OWNER,
    )
    creds = list_credentials(owner=OWNER)
    for c in creds:
        assert "credentials" not in c


def test_store_without_owner_is_refused(isolated_vault: Path) -> None:
    """Storing into the shared legacy namespace needs the explicit opt-in.

    Kills: removing the empty-owner refusal in store_credential, which would
    put every anonymous caller's credential into one pool.
    """
    result = store_credential(name="No Owner", credential_type="token", credentials={"t": "v"})
    assert result["success"] is False
    assert "owner is required" in result["error"]
    assert list(isolated_vault.glob("*.json")) == []
