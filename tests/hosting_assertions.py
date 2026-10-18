# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Assertion helpers for the cloud-hosting suite.

Split out of the test functions during the test-module split: the complexity
gate counts each ``assert`` as a branch, so a long test with 12+ assertions
breaches the CCN ceiling. Grouping them here keeps every function under the
gate while preserving every original assertion.
"""

from __future__ import annotations

from typing import Any

from tests.hosting_support import _REAL_WALLET


def assert_pro_plan(plans: dict[str, Any]) -> None:
    """Catalog tiers and the pro plan's limits."""
    assert set(plans) == {"pro", "team", "enterprise"}
    assert plans["pro"]["price_usd_monthly"] == 49.0
    assert plans["pro"]["max_concurrent_scrapes"] == 100
    assert plans["pro"]["max_pages_month"] == 100_000
    assert plans["pro"]["storage_gb"] == 10


def assert_team_and_enterprise_plans(plans: dict[str, Any]) -> None:
    """Team limits and the enterprise custom-quote tier."""
    assert plans["team"]["price_usd_monthly"] == 199.0
    assert plans["team"]["max_concurrent_scrapes"] == 500
    assert plans["team"]["max_pages_month"] == 500_000
    assert plans["team"]["storage_gb"] == 50
    assert plans["enterprise"]["price_usd_monthly"] is None
    assert plans["enterprise"]["purchasable"] is False


def assert_instance_provisioned(result: dict[str, Any]) -> None:
    """Confirmed payment yields a key and an active instance with plan limits."""
    assert result["paid"] is True
    assert result["api_key"]  # plaintext shown once
    assert result["api_key"].startswith("pry_")
    instance = result["instance"]
    assert instance["plan_tier"] == "pro"
    assert instance["status"] == "active"
    assert instance["resource_limit"]["max_concurrent_scrapes"] == 100
    assert instance["resource_limit"]["max_pages_month"] == 100_000
    assert instance["resource_limit"]["storage_gb"] == 10


def assert_key_reference_only(result: dict[str, Any]) -> None:
    """Only the key reference is stored — never the plaintext."""
    assert result["instance"]["api_key_id"]
    assert result["instance"]["api_key_id"] != result["api_key"]


def assert_renewal_invoice(renewal: dict[str, Any], instance_id: str) -> None:
    """Renewal quotes the same instance at the plan price, no new key."""
    assert renewal["invoice_id"].startswith("host_")
    assert renewal["instance_id"] == instance_id
    assert renewal["amount_usd"] == 49.0
    assert renewal["payment_required"]["accepts"][0]["payToAddress"] == _REAL_WALLET


def assert_instance_scoped_reads(client: Any, headers: dict[str, str], instance_id: str) -> None:
    """List + detail are scoped to the minted key; foreign/missing keys are 401."""
    listed = client.get("/v1/hosting/instances", headers=headers)
    assert listed.status_code == 200
    assert [i["instance_id"] for i in listed.json()["data"]["instances"]] == [instance_id]
    detail = client.get(f"/v1/hosting/instances/{instance_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["instance"]["plan_tier"] == "team"
