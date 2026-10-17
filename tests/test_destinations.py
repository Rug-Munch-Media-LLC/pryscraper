"""Tests for destinations.py — data egress functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pry.commerce.destinations import (
    DESTINATIONS,
    _data_to_rows,
    dispatch,
    write_to_email,
    write_to_slack,
)


@pytest.mark.asyncio
async def test_dispatch_unknown():
    result = await dispatch("nonexistent", {"data": "test"}, {})
    assert "error" in result


@pytest.mark.asyncio
async def test_dispatch_slack(monkeypatch: pytest.MonkeyPatch) -> None:
    # dispatch() reads the DESTINATIONS registry — patch the registry entry,
    # not the module attribute (the dict captured the original function at
    # import time, so patching the attribute is a no-op).
    fake = AsyncMock(return_value={"sent": True, "channel": "general"})
    monkeypatch.setitem(DESTINATIONS, "slack", fake)
    result = await dispatch("slack", {"text": "hello"}, {"webhook_url": "http://hook"})
    expected = {"sent": True, "channel": "general"}
    assert result == expected
    fake.assert_awaited_once()
    assert fake.await_args.kwargs["webhook_url"] == "http://hook"


@pytest.mark.asyncio
async def test_dispatch_slack_csv():
    # slack_csv is NOT a registered dispatch destination (see DESTINATIONS) —
    # dispatch must degrade with the unknown-destination error, never crash.
    result = await dispatch("slack_csv", {"data": [{"a": 1}]}, {"webhook_url": "http://hook"})
    assert result["success"] is False
    assert "Unknown destination" in result["error"]


@pytest.mark.asyncio
async def test_dispatch_email(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value={"sent": True})
    monkeypatch.setitem(DESTINATIONS, "email", fake)
    result = await dispatch("email", {"to": "a@b.com", "subject": "test", "body": "hello"}, {})
    expected = {"sent": True}
    assert result == expected
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_airtable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value={"created": 1})
    monkeypatch.setitem(DESTINATIONS, "airtable", fake)
    result = await dispatch(
        "airtable", {"records": [{"fields": {"a": 1}}], "base_id": "abc", "table": "xyz"}, {}
    )
    expected = {"created": 1}
    assert result == expected
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_googlesheets(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value={"updated": True})
    monkeypatch.setitem(DESTINATIONS, "googlesheets", fake)
    result = await dispatch(
        "googlesheets", {"data": [["a", "b"]], "sheet_id": "abc", "range": "A1"}, {}
    )
    expected = {"updated": True}
    assert result == expected
    fake.assert_awaited_once()


def test_data_to_rows_dict():
    result = _data_to_rows({"key": "value", "num": 42})
    assert isinstance(result, list)
    assert len(result) >= 1


def test_data_to_rows_list():
    result = _data_to_rows([{"a": 1}, {"a": 2}])
    assert len(result) >= 2


def test_data_to_rows_empty():
    result = _data_to_rows({})
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_write_to_email_no_smtp():
    with patch("pry.commerce.destinations._send_smtp", new_callable=AsyncMock) as m:
        m.return_value = {"sent": True}
        result = await write_to_email(
            recipient="a@b.com",
            subject="test",
            body="hello",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
        )
        assert result.get("sent") is True


@pytest.mark.asyncio
async def test_slack_empty_text():
    result = await write_to_slack("", "http://hook")
    assert "error" in result or "sent" in result
