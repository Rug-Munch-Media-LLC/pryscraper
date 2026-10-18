#!/usr/bin/env python3
"""Run MCP client conformance checks against a live Pry server.

Three layers, deliberately:

* **Wire matrix** (``mcp_conformance_transport``) — raw ``initialize`` requests
  at every revision Pry claims to speak, plus an unknown revision, each
  followed by ``tools/list``. This is the only way to request a *specific*
  revision: the official Python SDK's ``ClientSession.initialize()`` always
  sends ``LATEST_HANDSHAKE_VERSION``.
* **Official SDK session** (``mcp_conformance_sessions``) — ``mcp.ClientSession``
  over Streamable HTTP: initialize, list tools, call two tools (one free and
  one structured), list resources, subscribe to a resource, list prompts.
* **Modern session** — a 2026-07-28-only client: ``server/discover`` ->
  ``tools/list`` -> ``tools/call`` using per-request ``_meta`` and the
  ``MCP-Protocol-Version`` header, with no ``initialize``.

Usage::

    python scripts/mcp_conformance.py --url http://127.0.0.1:8006/ --key "$PRY_API_KEY"

Exit code 0 when every executed check passes, 1 otherwise. Without ``--key``
the tool-call checks are skipped (discovery still runs) and the matrix is
still printed.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mcp_conformance_modern import run_modern_session  # noqa: E402
from mcp_conformance_report import main, print_failures, print_matrix  # noqa: E402
from mcp_conformance_sessions import run_sdk_session  # noqa: E402
from mcp_conformance_transport import (  # noqa: E402
    ACCEPT,
    EXPECTED_CEILING,
    EXPECTED_TOOLS,
    MATRIX_VERSIONS,
    UNKNOWN_VERSION,
    run_wire_matrix,
)

__all__ = [
    "ACCEPT",
    "EXPECTED_CEILING",
    "EXPECTED_TOOLS",
    "MATRIX_VERSIONS",
    "UNKNOWN_VERSION",
    "main",
    "print_failures",
    "print_matrix",
    "run_modern_session",
    "run_sdk_session",
    "run_wire_matrix",
]


if __name__ == "__main__":
    raise SystemExit(main())
