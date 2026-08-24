"""Tests for destinations.py — data egress functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pry.commerce.destinations import (
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
async def test_dispatch_slack():
    with patch("pry.commerce.destinations.write_to_slack", new_callable=AsyncMock) as m:
        m.return_value = {"sent": True, "channel": "general"}
        result = await dispatch("slack", {"text": "hello"}, {"webhook_url": "http://hook"})
        assert result is not None


@pytest.mark.asyncio
async def test_dispatch_slack_csv():
    with patch("pry.commerce.destinations.write_to_slack_csv", new_callable=AsyncMock) as m:
        m.return_value = {"sent": True}
        result = await dispatch("slack_csv", {"data": [{"a": 1}]}, {"webhook_url": "http://hook"})
        assert result is not None


@pytest.mark.asyncio
async def test_dispatch_email():
    with patch("pry.commerce.destinations.write_to_email", new_callable=AsyncMock) as m:
        m.return_value = {"sent": True}
        result = await dispatch("email", {"to": "a@b.com", "subject": "test", "body": "hello"}, {})
        assert result is not None


@pytest.mark.asyncio
async def test_dispatch_airtable():
    with patch("pry.commerce.destinations.write_to_airtable", new_callable=AsyncMock) as m:
        m.return_value = {"created": 1}
        result = await dispatch(
            "airtable", {"records": [{"fields": {"a": 1}}], "base_id": "abc", "table": "xyz"}, {}
        )
        assert result is not None


@pytest.mark.asyncio
async def test_dispatch_googlesheets():
    with patch("pry.commerce.destinations.write_to_googlesheets", new_callable=AsyncMock) as m:
        m.return_value = {"updated": True}
        result = await dispatch(
            "googlesheets", {"data": [["a", "b"]], "sheet_id": "abc", "range": "A1"}, {}
        )
        assert result is not None


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
