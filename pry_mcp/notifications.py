"""Pry - MCP notification system.

Observer pattern for outgoing MCP notifications, MCP logging handler,
and notification helper functions.

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# Observer callbacks for outgoing MCP notifications (used by SSE transport).
# Each callback receives a JSON-RPC notification dict.
NotificationObserver = Callable[[dict[str, Any]], None]
_mcp_notification_observers: list[NotificationObserver] = []


def register_mcp_notification_observer(observer: NotificationObserver) -> None:
    """Register a callback that receives every outgoing MCP notification."""
    if observer not in _mcp_notification_observers:
        _mcp_notification_observers.append(observer)


def unregister_mcp_notification_observer(observer: NotificationObserver) -> None:
    """Remove a notification observer."""
    if observer in _mcp_notification_observers:
        _mcp_notification_observers.remove(observer)


def _send_mcp_notification(notification: dict[str, Any]) -> None:
    """Dispatch an MCP notification to all registered observers."""
    for observer in list(_mcp_notification_observers):
        try:
            observer(notification)
        except Exception as e:  # noqa: BLE001
            logger.warning("mcp_notification_observer_failed", extra={"error": str(e)})


class MCPLoggingHandler(logging.Handler):
    """Python logging handler that forwards log records as MCP notifications."""

    _LEVEL_MAP: ClassVar[dict[int, str]] = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warning",
        logging.ERROR: "error",
        logging.CRITICAL: "critical",
    }

    def __init__(self, server: Any) -> None:
        super().__init__()
        self.server = server

    def emit(self, record: logging.LogRecord) -> None:
        if not getattr(self.server, "_mcp_log_enabled", False):
            return
        min_level = getattr(self.server, "_mcp_log_level", logging.INFO)
        if record.levelno < min_level:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": self._LEVEL_MAP.get(record.levelno, "info"),
                "logger": record.name,
                "data": self.format(record),
            },
        }
        _send_mcp_notification(notification)


# Attach one global handler to the pry logger tree once a server is created.
_mcp_log_handler: MCPLoggingHandler | None = None


def _attach_mcp_logging(server: Any) -> None:
    """Attach the MCP forwarding log handler to the pry logger."""
    global _mcp_log_handler
    if _mcp_log_handler is None:
        _mcp_log_handler = MCPLoggingHandler(server)
        _mcp_log_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logging.getLogger("pry").addHandler(_mcp_log_handler)
        logging.getLogger("pry").setLevel(logging.DEBUG)


# Global server instance used by notification helpers.
_active_mcp_server: Any | None = None


def set_active_mcp_server(server: Any) -> None:
    """Mark an MCP server instance as active so helpers can use it."""
    global _active_mcp_server
    _active_mcp_server = server


def notify_resource_changed(uri: str) -> None:
    """Notify all connected MCP clients that a resource has changed."""
    _send_mcp_notification(
        {
            "jsonrpc": "2.0",
            "method": "notifications/resources/updated",
            "params": {"uri": uri},
        }
    )


def notify_resource_list_changed() -> None:
    """Notify all connected MCP clients that the resource list changed."""
    _send_mcp_notification(
        {
            "jsonrpc": "2.0",
            "method": "notifications/resources/list_changed",
        }
    )


def notify_tool_list_changed() -> None:
    """Notify all connected MCP clients that the tool list changed."""
    _send_mcp_notification(
        {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
        }
    )
