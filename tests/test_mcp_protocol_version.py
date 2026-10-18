"""MCP protocol revision is one constant and is negotiated, never guessed."""

from __future__ import annotations

from pry_mcp.constants import (
    MCP_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    negotiate_protocol_version,
)


def test_ceiling_is_the_latest_official_revision() -> None:
    assert MCP_PROTOCOL_VERSION == "2026-07-28"
    assert MCP_PROTOCOL_VERSION in SUPPORTED_PROTOCOL_VERSIONS


def test_negotiation_echoes_a_supported_client_revision() -> None:
    assert negotiate_protocol_version("2025-06-18") == "2025-06-18"
    assert negotiate_protocol_version("2025-11-25") == "2025-11-25"


def test_negotiation_falls_back_to_the_ceiling() -> None:
    assert negotiate_protocol_version(None) == MCP_PROTOCOL_VERSION
    assert negotiate_protocol_version("") == MCP_PROTOCOL_VERSION
    assert negotiate_protocol_version("2099-01-01") == MCP_PROTOCOL_VERSION


def test_no_hardcoded_revision_outside_the_constant() -> None:
    """Handlers must import the constant instead of spelling the revision."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "pry_mcp").rglob("*.py"):
        if path.name == "constants.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "2026-07-28":
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []
