# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for white-label agency dashboard."""

from agency import (
    check_client_quota,
    create_agency,
    create_client,
    get_agency_analytics,
    list_clients,
    update_agency_branding,
    update_client_quota,
)


def test_create_agency() -> None:
    result = create_agency("Test Agency", "owner@test.com")
    assert result["success"] is True
    assert result["agency"]["name"] == "Test Agency"
    assert result["agency"]["features"]["white_label"] is True


def test_create_agency_with_custom_branding() -> None:
    result = create_agency(
        "Branded Co", "owner@branded.com", custom_domain="scrape.branded.com", brand_color="#ff0000"
    )
    assert result["success"] is True
    assert result["agency"]["custom_domain"] == "scrape.branded.com"
    assert result["agency"]["brand_color"] == "#ff0000"


def test_update_branding() -> None:
    result = create_agency("Update Test", "update@test.com")
    agency_id = result["agency"]["id"]
    updated = update_agency_branding(agency_id, brand_color="#00ff00", name="Updated Agency")
    assert updated["success"] is True
    assert updated["agency"]["brand_color"] == "#00ff00"
    assert updated["agency"]["name"] == "Updated Agency"


def test_create_client() -> None:
    agency = create_agency("Client Test", "client@test.com")
    agency_id = agency["agency"]["id"]
    client = create_client(agency_id, "Test Client", "client@acme.com", monthly_quota=5000)
    assert client["success"] is True
    assert "api_key" not in client["client"]  # API key should not be exposed


def test_list_clients() -> None:
    agency = create_agency("List Test", "list@test.com")
    agency_id = agency["agency"]["id"]
    create_client(agency_id, "Client A", "a@test.com")
    create_client(agency_id, "Client B", "b@test.com")
    clients = list_clients(agency_id)
    assert len(clients) >= 2


def test_client_quota() -> None:
    agency = create_agency("Quota Test", "quota@test.com")
    client = create_client(agency["agency"]["id"], "Quota Client", "q@test.com", monthly_quota=100)
    client_id = client["client"]["id"]

    # Check initial quota
    check = check_client_quota(client_id)
    assert check["success"] is True
    assert check["percent_used"] == 0.0

    # Update quota
    update_client_quota(client_id, 500)
    check2 = check_client_quota(client_id)
    assert check2["quota"] == 500


def test_get_analytics() -> None:
    agency = create_agency("Analytics Test", "analytics@test.com")
    result = get_agency_analytics(agency["agency"]["id"])
    assert "total_clients" in result
    assert "total_usage" in result
