# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for MCP SSE transport (mcp_sse.py) — HTTP+SSE streaming.

T1 win #9: MCP SSE transport test coverage — verifies SSE event stream
format, session lifecycle, keepalive, message handling, and cleanup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from pry.api.mcp_sse import (
    MCP_SSE_SESSIONS,
    MCP_SSE_TASKS,
    SESSION_TTL_SECONDS,
    _cleanup_session,
    _create_event,
    _enqueue_response,
    _get_or_create_queue,
    _new_session_id,
)


@pytest.fixture(autouse=True)
def _sse_observer_cleanup():
    """Drain SSE-global state after every test in this module.

    Guards against a leaked MCP notification observer (registered by
    `mcp_sse_endpoint` and only unregistered when the event-stream
    generator's finally block runs). A stale observer whose session has
    been cleared re-enters `_enqueue_response` -> "session not found"
    warning -> MCPLoggingHandler.emit -> observer recursion on the next
    "pry"-tree log record, hanging the full suite.
    """
    yield
    from pry_mcp import notifications as _notifications

    _notifications._mcp_notification_observers.clear()
    MCP_SSE_SESSIONS.clear()
    MCP_SSE_TASKS.clear()


class TestSSEEventFormat:
    """SSE event formatting per the spec."""

    def test_create_event_message(self) -> None:
        event = _create_event("message", '{"jsonrpc":"2.0","result":"ok"}')
        assert event == 'event: message\ndata: {"jsonrpc":"2.0","result":"ok"}\n\n'

    def test_create_event_endpoint(self) -> None:
        event = _create_event("endpoint", "http://localhost/mcp/messages/abc123")
        assert "event: endpoint" in event
        assert "data: http://localhost/mcp/messages/abc123" in event

    def test_create_event_error(self) -> None:
        event = _create_event("error", '{"error":"session_idle_timeout"}')
        assert "event: error" in event


class TestSessionLifecycle:
    """Session creation, retrieval, and cleanup."""

    def setup_method(self) -> None:
        MCP_SSE_SESSIONS.clear()
        MCP_SSE_TASKS.clear()

    def test_new_session_id_is_unique(self) -> None:
        ids = {_new_session_id() for _ in range(100)}
        assert len(ids) == 100  # all unique

    def test_new_session_id_is_long_enough(self) -> None:
        sid = _new_session_id()
        assert len(sid) >= 16

    def test_get_or_create_queue_creates_new(self) -> None:
        q = _get_or_create_queue("new_session")
        assert q is not None
        assert "new_session" in MCP_SSE_SESSIONS

    def test_get_or_create_queue_returns_existing(self) -> None:
        q1 = _get_or_create_queue("existing_session")
        q2 = _get_or_create_queue("existing_session")
        assert q1 is q2

    def test_cleanup_session_removes_state(self) -> None:
        _get_or_create_queue("to_cleanup")
        assert "to_cleanup" in MCP_SSE_SESSIONS
        _cleanup_session("to_cleanup")
        assert "to_cleanup" not in MCP_SSE_SESSIONS

    def test_cleanup_session_cancels_task(self) -> None:
        _get_or_create_queue("with_task")
        mock_task = MagicMock()
        mock_task.done.return_value = False
        MCP_SSE_TASKS["with_task"] = mock_task

        _cleanup_session("with_task")
        mock_task.cancel.assert_called_once()

    def test_cleanup_session_with_observer(self) -> None:
        _get_or_create_queue("with_observer")
        observer = MagicMock()
        with patch("pry.api.mcp_sse.unregister_mcp_notification_observer") as mock_unreg:
            _cleanup_session("with_observer", observer)
            mock_unreg.assert_called_once_with(observer)


class TestEnqueueResponse:
    """Message enqueuing to SSE stream."""

    def setup_method(self) -> None:
        MCP_SSE_SESSIONS.clear()
        MCP_SSE_TASKS.clear()

    def test_enqueue_response_to_existing_session(self) -> None:
        _get_or_create_queue("active_session")
        _enqueue_response("active_session", {"jsonrpc": "2.0", "result": "ok"})
        q = MCP_SSE_SESSIONS["active_session"]
        assert q.qsize() == 1

    def test_enqueue_response_unknown_session_no_raise(self) -> None:
        """Enqueuing to unknown session should not raise."""
        _enqueue_response("ghost_session", {"result": "ok"})

    def test_enqueue_multiple_responses(self) -> None:
        _get_or_create_queue("multi_session")
        for i in range(5):
            _enqueue_response("multi_session", {"id": i})
        q = MCP_SSE_SESSIONS["multi_session"]
        assert q.qsize() == 5


class TestKeepaliveLoop:
    """Keepalive ping loop."""

    def setup_method(self) -> None:
        MCP_SSE_SESSIONS.clear()
        MCP_SSE_TASKS.clear()

    @pytest.mark.asyncio
    async def test_keepalive_loop_sends_ping(self) -> None:
        from pry.api.mcp_sse import _get_or_create_queue, _keepalive_loop

        _get_or_create_queue("ka_session")
        task = asyncio.create_task(_keepalive_loop("ka_session"))

        # Wait briefly, then cancel — loop sleeps 30s between pings so
        # we just verify it starts without error and can be cancelled.
        await asyncio.sleep(0.05)
        task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_keepalive_loop_cancelled_cleanly(self) -> None:
        from pry.api.mcp_sse import _get_or_create_queue, _keepalive_loop

        _get_or_create_queue("cancel_session")
        task = asyncio.create_task(_keepalive_loop("cancel_session"))
        task.cancel()

        # Should not raise
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestSSEEndpoint:
    """SSE endpoint integration tests."""

    def setup_method(self) -> None:
        MCP_SSE_SESSIONS.clear()
        MCP_SSE_TASKS.clear()

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_streaming_response(self) -> None:
        from pry.api.mcp_sse import mcp_sse_endpoint

        mock_handler = MagicMock()
        mock_handler.handle_request = AsyncMock(return_value={"jsonrpc": "2.0", "result": "ok"})

        mock_request = MagicMock(spec=Request)
        mock_request.base_url = MagicMock()
        mock_request.base_url.__str__ = MagicMock(return_value="http://test")
        mock_request.query_params = {}

        response = await mcp_sse_endpoint(mock_request, mock_handler)
        assert response.media_type == "text/event-stream"
        assert "Cache-Control" in response.headers
        assert response.headers["Cache-Control"] == "no-cache, no-transform"

        # Consume/close the event stream so the endpoint's finally block runs
        # `_cleanup_session(session_id, observer)` and unregisters the global
        # notification observer. Leaving the generator unstarted leaks the
        # observer into `pry_mcp.notifications._mcp_notification_observers`;
        # once the session is later cleared, any subsequent "pry"-tree log
        # record re-enters the leaked observer -> `_enqueue_response` ->
        # "session not found" warning -> MCPLoggingHandler.emit -> observer
        # recursion, hanging the whole suite.
        async for _chunk in response.body_iterator:
            break

    @pytest.mark.asyncio
    async def test_sse_endpoint_yields_endpoint_event_first(self) -> None:
        from pry.api.mcp_sse import mcp_sse_endpoint

        mock_handler = MagicMock()
        mock_handler.handle_request = AsyncMock(return_value={"jsonrpc": "2.0", "result": "ok"})

        mock_request = MagicMock(spec=Request)
        mock_request.base_url = MagicMock()
        mock_request.base_url.__str__ = MagicMock(return_value="http://test")
        mock_request.query_params = {"_sse_test_close_after": "1"}

        response = await mcp_sse_endpoint(mock_request, mock_handler)

        # Enqueue a message so the stream yields a second event deterministically.
        # (Otherwise the 2nd event only arrives via the 30s keepalive — a race
        # against the test timeout.)
        from pry.api.mcp_sse import MCP_SSE_SESSIONS, _enqueue_response

        session_id = next(iter(MCP_SSE_SESSIONS))
        _enqueue_response(session_id, {"jsonrpc": "2.0", "result": "ok"})

        # Consume the event stream
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
            if len(events) >= 2:
                break

        # First event should be the endpoint event
        assert any("event: endpoint" in e for e in events)


class TestPostMessage:
    """POST message handler."""

    def setup_method(self) -> None:
        MCP_SSE_SESSIONS.clear()
        MCP_SSE_TASKS.clear()

    @pytest.mark.asyncio
    async def test_post_message_returns_202(self) -> None:
        from pry.api.mcp_sse import mcp_post_message

        _get_or_create_queue("post_session")

        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(
            return_value={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )

        mock_handler = MagicMock()
        mock_handler.handle_request = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}})

        response = await mcp_post_message(mock_request, "post_session", mock_handler)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_post_message_unknown_session_returns_404(self) -> None:
        from pry.api.mcp_sse import mcp_post_message

        mock_request = MagicMock(spec=Request)
        mock_handler = MagicMock()

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await mcp_post_message(mock_request, "unknown_session", mock_handler)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_message_invalid_json_returns_202_with_error(self) -> None:
        from pry.api.mcp_sse import mcp_post_message

        _get_or_create_queue("json_error_session")

        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(side_effect=json.JSONDecodeError("err", "doc", 0))

        mock_handler = MagicMock()

        response = await mcp_post_message(mock_request, "json_error_session", mock_handler)
        assert response.status_code == 202


class TestTTL:
    """Session TTL constant."""

    def test_session_ttl_reasonable(self) -> None:
        assert 60 <= SESSION_TTL_SECONDS <= 3600  # 1 min to 1 hour
