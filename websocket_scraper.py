"""Pry — WebSocket and Server-Sent Events (SSE) scraping.
Modern SPAs (Twitter, Discord, stock tickers) and real-time apps use WebSockets
and SSE for data delivery. This scraper connects to these endpoints and
captures the data stream."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class WebSocketScraper:
    """Scrape data from WebSocket and SSE endpoints."""

    def __init__(self, max_messages: int = 100, timeout: int = 30) -> None:
        self.max_messages = max_messages
        self.timeout = timeout

    async def scrape_websocket(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        message_filter: str = "",
        protocols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Connect to a WebSocket and capture messages.

        Args:
            url: ws:// or wss:// URL
            headers: Optional HTTP headers for the upgrade request
            message_filter: Only return messages containing this string
            protocols: WebSocket subprotocols
        """
        try:
            import websockets
        except ImportError:
            return {
                "success": False,
                "error": "websockets not installed. Run: pip install websockets",
            }

        messages: list[dict[str, Any]] = []
        try:
            async with websockets.connect(
                url,
                extra_headers=headers or {},
                subprotocols=protocols,
            ) as ws:
                start = time.time()
                while (
                    len(messages) < self.max_messages
                    and (time.time() - start) < self.timeout
                ):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    except TimeoutError:
                        break
                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", errors="replace")
                    if message_filter and message_filter not in msg:
                        continue
                    try:
                        parsed: Any = json.loads(msg)
                    except (json.JSONDecodeError, ValueError):
                        parsed = msg
                    messages.append(
                        {"data": parsed, "raw": msg, "received_at": time.time()}
                    )
        except Exception as e:
            return {"success": False, "error": str(e)[:300]}

        return {
            "success": True,
            "url": url,
            "messages": messages,
            "count": len(messages),
        }

    async def scrape_sse(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        event_filter: str = "",
        max_events: int = 50,
    ) -> dict[str, Any]:
        """Connect to a Server-Sent Events endpoint and capture events."""
        from client import get_client

        client = await get_client()
        events: list[dict[str, Any]] = []
        try:
            async with client.stream(
                "GET", url, headers=headers or {}, timeout=self.timeout
            ) as resp:
                event_type = "message"
                data_buf: list[str] = []
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_buf.append(line.split(":", 1)[1].strip())
                    elif line.startswith(":"):
                        # SSE comment line — ignore
                        continue
                    else:
                        if data_buf:
                            raw_data = "\n".join(data_buf)
                            try:
                                parsed: Any = json.loads(raw_data)
                            except (json.JSONDecodeError, ValueError):
                                parsed = raw_data
                            if event_filter and event_filter not in str(parsed):
                                data_buf = []
                                event_type = "message"
                                continue
                            events.append(
                                {
                                    "event": event_type,
                                    "data": parsed,
                                    "raw": raw_data,
                                }
                            )
                            data_buf = []
                            event_type = "message"
                    if len(events) >= max_events:
                        break
            return {
                "success": True,
                "url": url,
                "events": events,
                "count": len(events),
            }
        except Exception as e:
            return {"success": False, "error": str(e)[:300]}
