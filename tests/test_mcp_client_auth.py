# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Auth boundary: loopback is not a credential once PRY_API_KEY is configured."""

from __future__ import annotations

from typing import Any

import httpx

from tests.conformance_support import (  # noqa: F401 - fixtures
    auth_key,
    live_server,
)


def test_tools_call_requires_the_bearer_header(live_server: Any, auth_key: str) -> None:
    """Loopback is not a credential once PRY_API_KEY is configured."""
    url, key = live_server
    call = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "pry_scrape_methods", "arguments": {}},
    }
    with httpx.Client(timeout=10) as client:
        init = client.post(
            url,
            headers={"Accept": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        session_id = init.headers["mcp-session-id"]
        headers = {"Accept": "application/json", "Mcp-Session-Id": session_id}

        anonymous = client.post(url, headers=headers, json=call)
        assert anonymous.status_code == 401
        assert anonymous.json()["error"]["code"] == -32001

        authorized = client.post(
            url, headers={**headers, "Authorization": f"Bearer {key}"}, json=call
        )
        assert authorized.status_code == 200
        assert authorized.json()["result"]["isError"] is False
