# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for enterprise SSO / auth connector."""

from auth_connector import (
    SSO_PROVIDERS,
    delete_credential,
    list_credentials,
    store_credential,
)


def test_sso_providers() -> None:
    assert "okta" in SSO_PROVIDERS
    assert "azure_ad" in SSO_PROVIDERS
    assert "google_workspace" in SSO_PROVIDERS
    assert "onelogin" in SSO_PROVIDERS


def test_store_credential() -> None:
    result = store_credential(
        name="Test Login",
        credential_type="password",
        credentials={"username": "admin", "password": "secret123"},
        target_url="https://example.com/login",
    )
    assert result["success"] is True
    assert "credential_id" in result
    assert result["credential"]["name"] == "Test Login"


def test_store_and_list() -> None:
    store_credential(
        name="List Test",
        credential_type="api_key",
        credentials={"key": "abc123"},
    )
    creds = list_credentials()
    names = [c["name"] for c in creds]
    assert "List Test" in names


def test_store_and_delete() -> None:
    result = store_credential(
        name="Delete Test",
        credential_type="password",
        credentials={"user": "test"},
    )
    cred_id = result["credential"]["id"]
    deleted = delete_credential(cred_id)
    assert deleted is True
    assert delete_credential(cred_id) is False


def test_list_no_secrets() -> None:
    store_credential(
        name="Secret Test",
        credential_type="password",
        credentials={"password": "super-secret-value"},
    )
    creds = list_credentials()
    for c in creds:
        assert "credentials" not in c
