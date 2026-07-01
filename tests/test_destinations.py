"""Tests for business integrations."""

from destinations import (
    SUPPORTED_DESTINATIONS,
    _data_to_rows,
    dispatch,
    write_to_email,
    write_to_slack,
)


def test_supported_destinations() -> None:
    assert "slack" in SUPPORTED_DESTINATIONS
    assert "googlesheets" in SUPPORTED_DESTINATIONS
    assert "airtable" in SUPPORTED_DESTINATIONS
    assert "email" in SUPPORTED_DESTINATIONS


def test_dispatch_unknown() -> None:
    import asyncio

    result = asyncio.run(dispatch("unknown", {}, {}))
    assert result["success"] is False
    assert "unknown" in result["error"]


def test_data_to_rows_dict() -> None:
    data = {"name": "Alice", "age": 30}
    rows = _data_to_rows(data)
    assert rows[0] == ["name", "age"]
    assert rows[1] == ["Alice", "30"]


def test_data_to_rows_list() -> None:
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    rows = _data_to_rows(data)
    assert rows[0] == ["a", "b"]
    assert len(rows) == 3


def test_data_to_rows_empty() -> None:
    rows = _data_to_rows([])
    assert len(rows) == 1


def test_email_fallback_generates_mailto() -> None:
    import asyncio

    result = asyncio.run(
        write_to_email(
            recipient="test@example.com",
            subject="Test",
            body="Hello from Pry",
        )
    )
    assert result["success"] is True
    assert "mailto:" in result.get("mailto_link", "")


def test_slack_write_fails_without_url() -> None:
    import asyncio

    result = asyncio.run(write_to_slack(webhook_url="", message="test"))
    assert result["success"] is False
