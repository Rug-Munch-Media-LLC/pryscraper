"""Tests for CRM reverse ETL."""

from crm_sync import (
    _map_to_hubspot,
    _map_to_salesforce,
    sync_to_close,
    sync_to_hubspot,
    sync_to_pipedrive,
    sync_to_salesforce,
)


def test_sync_salesforce_no_creds() -> None:
    import asyncio

    result = asyncio.run(
        sync_to_salesforce([{"name": "Test Lead", "email": "test@test.com"}], "Lead", "", "")
    )
    assert result["success"] is False
    assert result["synced"] == 0


def test_sync_hubspot_no_creds() -> None:
    import asyncio

    result = asyncio.run(sync_to_hubspot([{"email": "test@test.com"}], "contacts", ""))
    assert result["success"] is False


def test_sync_pipedrive_no_creds() -> None:
    import asyncio

    result = asyncio.run(sync_to_pipedrive([{"name": "Test"}], "person", "", ""))
    assert result["success"] is False


def test_sync_close_no_creds() -> None:
    import asyncio

    result = asyncio.run(sync_to_close([{"name": "Test"}], "lead", ""))
    assert result["success"] is False


def test_map_to_salesforce_lead() -> None:
    data = {"name": "John Doe", "email": "john@test.com", "company": "Acme Inc"}
    mapped = _map_to_salesforce(data, "Lead")
    assert mapped.get("LastName") == "John Doe"
    assert mapped.get("Email") == "john@test.com"
    assert mapped.get("Company") == "Acme Inc"


def test_map_to_hubspot_contact() -> None:
    data = {"email": "jane@test.com", "first_name": "Jane", "phone": "555-0100"}
    mapped = _map_to_hubspot(data, "contacts")
    assert mapped.get("email") == "jane@test.com"
    assert mapped.get("firstname") == "Jane"
    assert mapped.get("phone") == "555-0100"
