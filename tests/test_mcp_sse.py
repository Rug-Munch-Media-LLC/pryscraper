"""Tests for mcp_sse.py — MCP HTTP+SSE transport server."""

from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_sse import (
    _new_session_id,
    _create_event,
    _get_or_create_queue,
    _enqueue_response,
    _cleanup_session,
    MCP_SSE_SESSIONS,
    MCP_SSE_TASKS,
    SESSION_TTL_SECONDS,
)


def setup_method():
    MCP_SSE_SESSIONS.clear()
    MCP_SSE_TASKS.clear()


def test_new_session_id():
    sid = _new_session_id()
    assert len(sid) > 10
    assert isinstance(sid, str)


def test_create_event():
    event = _create_event("message", '{"ok":true}')
    assert "event: message" in event
    assert "data: {" in event


def test_get_or_create_queue_new():
    q = _get_or_create_queue("test_sid")
    assert q is not None
    assert "test_sid" in MCP_SSE_SESSIONS


def test_get_or_create_queue_existing():
    _get_or_create_queue("test_sid")
    q2 = _get_or_create_queue("test_sid")
    assert q2 is MCP_SSE_SESSIONS["test_sid"]


def test_enqueue_response():
    _get_or_create_queue("sid1")
    _enqueue_response("sid1", {"jsonrpc": "2.0", "result": "ok"})
    q = MCP_SSE_SESSIONS["sid1"]
    assert q.qsize() == 1


def test_enqueue_response_unknown_session():
    _enqueue_response("no_such_sid", {"result": "ok"})
    # Should not raise


def test_cleanup_session():
    """Cleanup session with a mock task."""
    _get_or_create_queue("sid_clean")
    # Use a done task to avoid event loop issues
    task = asyncio.Future()
    task.set_result(None)
    MCP_SSE_TASKS["sid_clean"] = task
    _cleanup_session("sid_clean")
    assert "sid_clean" not in MCP_SSE_SESSIONS


def test_cleanup_session_with_observer():
    observer = MagicMock()
    _get_or_create_queue("sid_obs")
    with patch("mcp_sse.unregister_mcp_notification_observer") as mock_unreg:
        _cleanup_session("sid_obs", observer)
        mock_unreg.assert_called_once_with(observer)


def test_session_ttl_constant():
    assert SESSION_TTL_SECONDS > 0


@pytest.mark.asyncio
async def test_keepalive_loop_cancelled():
    """Keepalive loop exits cleanly on cancel."""
    from mcp_sse import _keepalive_loop, _get_or_create_queue

    _get_or_create_queue("sid_ka")
    task = asyncio.create_task(_keepalive_loop("sid_ka"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_mcp_sse_endpoint():
    """SSE endpoint produces a StreamingResponse."""
    from mcp_sse import mcp_sse_endpoint
    from fastapi import Request

    mock_handler = MagicMock()
    mock_handler.handle_request = AsyncMock(return_value={"jsonrpc": "2.0", "result": "ok"})
    mock_request = MagicMock(spec=Request)
    mock_request.base_url = MagicMock()
    mock_request.base_url.__str__ = MagicMock(return_value="http://test")

    response = await mcp_sse_endpoint(mock_request, mock_handler)
    assert response is not None
    assert hasattr(response, "body_iterator") or hasattr(response, "media_type")
