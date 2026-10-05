# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP server quality audit tests (split by concern).

Layers:

1. **Tool metadata** — ``test_tool_metadata.py``.
2. **Round-trip ``tools/call``** — ``test_tool_roundtrips.py``.
3. **Streamable HTTP transport compliance** — ``test_transport_compliance.py``.
4. **Tool-count consistency with registry files** — ``test_registry_consistency.py``.
"""
