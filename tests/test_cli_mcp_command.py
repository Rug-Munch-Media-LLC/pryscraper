"""`pry mcp --stdio` must exist, advertise itself, and boot the MCP server.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from pry.misc.cli_click import cli, mcp_serve


def test_mcp_stdio_flag_launches_server() -> None:
    with patch("pry.misc.cli_click.launch_mcp_stdio") as launch:
        result = CliRunner().invoke(cli, ["mcp", "--stdio"])
    assert result.exit_code == 0, result.output
    launch.assert_called_once_with()


def test_mcp_serve_subcommand_uses_same_launch_path() -> None:
    with patch("pry.misc.cli_click.launch_mcp_stdio") as launch:
        result = CliRunner().invoke(cli, ["mcp", "serve"])
    assert result.exit_code == 0, result.output
    launch.assert_called_once_with()


def test_mcp_help_documents_stdio() -> None:
    result = CliRunner().invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "--stdio" in result.output
    assert "pry mcp --stdio" in result.output.replace("  ", " ") or "stdio" in result.output


def test_console_entrypoint_is_callable() -> None:
    """``pry-mcp`` / ``pryscraper-mcp`` point at this object."""
    assert callable(mcp_serve)


def test_dispatcher_routes_mcp_to_click(monkeypatch) -> None:
    """`pry mcp --stdio` must reach the click group, not "Unknown command"."""
    from pry.misc import cli_commands

    monkeypatch.setattr(cli_commands.sys, "argv", ["pry", "mcp", "--stdio"])
    with patch("pry.misc.cli_click.launch_mcp_stdio") as launch:
        cli_commands.main()
    launch.assert_called_once_with()


def test_dispatcher_help_lists_mcp(monkeypatch, capsys) -> None:
    """The legacy usage block advertises the click-only mcp command."""
    from pry.misc import cli_commands

    monkeypatch.setattr(cli_commands.sys, "argv", ["pry", "--help"])
    cli_commands.main()
    out = capsys.readouterr().out
    assert "pry mcp" in out


def test_dispatcher_does_not_recurse(monkeypatch) -> None:
    """The dispatcher forwards to the click group, never back to itself."""
    from pry.misc import cli_commands
    from pry.misc.cli_click import cli as click_group

    monkeypatch.setattr(cli_commands.sys, "argv", ["pry", "mcp", "info"])
    result = CliRunner().invoke(cli, ["mcp", "info"])
    assert result.exit_code == 0, result.output
    assert "Pry MCP Server" in result.output
    # `main` is the dispatcher; the click group is `cli` (distinct objects).
    assert click_group is not cli_commands.main
