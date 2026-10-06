"""Pry — WebSocket and Server-Sent Events (SSE) scraping.
Modern SPAs (Twitter, Discord, stock tickers) and real-time apps use WebSockets
and SSE for data delivery. This scraper connects to these endpoints and
captures the data stream."""

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import _validate_host, validate_url

logger = logging.getLogger(__name__)

_WS_SCHEMES = {"ws", "wss"}


def validate_websocket_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate a ``ws://``/``wss://`` URL for SSRF safety.

    ``url_guard.validate_url`` only accepts http/https, so WebSocket URLs were
    previously left ungated. This host-level guard reuses url_guard's
    private/reserved IP ranges and internal-hostname rules to reject
    loopback, link-local, cloud-metadata, CGNAT, and internal host targets
    (``ws://127.0.0.1``, ``ws://169.254.169.254``, ``ws://[::1]``, ...).

    Args:
        url: The WebSocket URL to validate.
        resolve_dns: If True, reject hostnames that resolve to private IPs
            (guards DNS-rebinding vectors, same default as ``validate_url``).

    Returns:
        The validated URL (unchanged).

    Raises:
        InvalidRequestError: If the URL is unsafe.
    """
    if not url:
        raise _ws_error("URL is empty", url)

    parsed = urlparse(url)

    if parsed.scheme not in _WS_SCHEMES:
        raise _ws_error(
            f"URL scheme {parsed.scheme} is not allowed (only ws/wss for WebSocket endpoints)",
            url,
        )

    if parsed.username or parsed.password:
        raise _ws_error("URL must not contain embedded credentials (user:password@)", url)

    hostname = parsed.hostname or ""
    if not hostname:
        raise _ws_error("URL must have a valid hostname", url)

    # Reject raw private IPs, internal hostnames, and DNS resolution to
    # private IPs (shared host-validation logic from url_guard).
    try:
        _validate_host(hostname, resolve_dns=resolve_dns, error_cls=InvalidRequestError)
    except InvalidRequestError as e:
        raise _ws_error(str(e), url) from None

    return url


def _ws_error(message: str, url: str) -> InvalidRequestError:
    """Build a structured InvalidRequestError for WebSocket validation."""
    logger.warning("websocket_url_rejected", extra={"url": url, "reason": message})
    return InvalidRequestError(message, details={"url": url, "reason": message})


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
        validate_websocket_url(url)
        try:
            import websockets
        except ImportError:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {
                "success": False,
                "error": "websockets not installed. Run: pip install websockets",
            }

        messages: list[dict[str, Any]] = []
        try:
            async with websockets.connect(
                url,
                extra_headers=headers or {},
                subprotocols=protocols,  # type: ignore[arg-type]  # websockets expects Sequence[Subprotocol]; runtime OK
            ) as ws:
                start = time.time()
                while len(messages) < self.max_messages and (time.time() - start) < self.timeout:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    except TimeoutError:
                        logger.warning("silent_exception_swallowed", exc_info=True)
                        break
                    if isinstance(msg, bytes):
                        msg = msg.decode("utf-8", errors="replace")
                    if message_filter and message_filter not in msg:
                        continue
                    try:
                        parsed: Any = json.loads(msg)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning("silent_exception_swallowed", exc_info=True)
                        parsed = msg
                    messages.append({"data": parsed, "raw": msg, "received_at": time.time()})
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("silent_exception_swallowed", exc_info=True)
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
        from pry.api.client import get_client

        validate_url(url)
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
                                logger.warning("silent_exception_swallowed", exc_info=True)
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
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {"success": False, "error": str(e)[:300]}
