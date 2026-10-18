"""Legacy argv dispatch for the Pry CLI (delegates to cli_impl)."""

# ruff: noqa: T201 - a CLI writes to stdout by design

from __future__ import annotations

import sys
from typing import Any

import click

from pry.misc.cli_click import cli
from pry.misc.cli_helpers import BOLD, CYAN, NC, RED, VERSION
from pry.misc.cli_impl import (
    cmd_batch,
    cmd_completions,
    cmd_crawl,
    cmd_migrate,
    cmd_open,
    cmd_parse,
    cmd_run,
    cmd_screenshot,
    cmd_serve,
    cmd_watch,
)


def _print_usage() -> None:
    """Print the standard Pry usage block (no exit)."""
    print(f"{BOLD}Pry v{VERSION}{NC} — Pry open any website. {CYAN}pryscraper.com{NC}")
    print()
    print(f"  {BOLD}Usage:{NC}")
    print(f"    {CYAN}pry open <url>{NC}              Scrape a URL")
    print(f"    {CYAN}pry watch <url>{NC}             Monitor for changes")
    print(f"    {CYAN}pry crawl <url>{NC}             Crawl a site")
    print(f"    {CYAN}pry batch <file>{NC}            Batch scrape from a file")
    print(f"    {CYAN}pry parse <url>{NC}             Parse a document")
    print(f"    {CYAN}pry ss <url>{NC}                Take a screenshot")
    print(f"    {CYAN}pry run [pry.yml]{NC}           Execute job file")
    print(f"    {CYAN}pry migrate{NC}                 Run database migrations")
    print(f"    {CYAN}pry serve{NC}                   Start the server")
    print(f"    {CYAN}pry completions{NC}             Install autocomplete")
    print(f"    {CYAN}pry proxy ...{NC}               Manage proxy providers and signup")
    print(f"    {CYAN}pry mcp [--stdio]{NC}          MCP server for AI agents (stdio)")
    print()
    print(f"  {BOLD}Examples:{NC}")
    print("    pry open https://example.com")
    print("    pry open https://store.com --json --schema product.json")
    print("    pry watch https://site.com --webhook slack://...")
    print("    pry crawl https://docs.com --max-pages 20 -o data.json")
    print('    pry batch urls.txt --template \'{"price":".price"}\'')
    print("    pry run")
    print("    pry serve")
    print("    pry proxy list")
    print("    pry proxy signup brightdata")
    print("    pry mcp --stdio")
    print("    pry mcp serve")
    print()
    print(f"  {BOLD}Settings:{NC}")
    print("    PRY_URL=http://localhost:8005    (default)")


# ── Per-command dispatch helpers (extracted from main() — audit P2) ─────────


def _opt_value(flag: str, default: str | None = None) -> str | None:
    """Value of ``--flag <value>`` from sys.argv, or ``default``."""
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _int_opt_value(flag: str, default: int) -> int:
    """Int value of ``--flag <value>`` from sys.argv, or ``default``."""
    return int(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def _dispatch_open_like(args: list[str]) -> None:
    """``open`` | ``get`` | ``scrape``"""
    url = args[0] if args else input("URL: ")
    opts: dict[str, Any] = {"output_json": "--json" in sys.argv, "timeout": 30}
    if "--schema" in sys.argv:
        opts["schema_path"] = sys.argv[sys.argv.index("--schema") + 1]
    if "--timeout" in sys.argv:
        opts["timeout"] = int(sys.argv[sys.argv.index("--timeout") + 1])
    if "--offset" in sys.argv:
        opts["offset"] = int(sys.argv[sys.argv.index("--offset") + 1])
    if "--limit" in sys.argv:
        opts["limit"] = int(sys.argv[sys.argv.index("--limit") + 1])
    cmd_open(url, **opts)


def _dispatch_watch(args: list[str]) -> None:
    url = args[0] if args else input("URL: ")
    webhook = sys.argv[sys.argv.index("--webhook") + 1] if "--webhook" in sys.argv else ""
    cmd_watch(url, webhook)


def _dispatch_crawl(args: list[str]) -> None:
    url = args[0] if args else input("URL: ")
    max_p = _int_opt_value("--max-pages", 10)
    out = _opt_value("-o")
    cmd_crawl(url, max_p, out)


def _dispatch_batch(args: list[str]) -> None:
    fp = args[0] if args else input("File: ")
    tmpl = _opt_value("--template", "") or ""
    cmd_batch(fp, tmpl)


def _dispatch_parse(args: list[str]) -> None:
    url = args[0] if args else input("URL: ")
    cmd_parse(url)


def _dispatch_screenshot(args: list[str]) -> None:
    url = args[0] if args else input("URL: ")
    out = _opt_value("-o")
    cmd_screenshot(url, out)


def _dispatch_run(args: list[str]) -> None:
    cmd_run(args[0] if args else "pry.yml")


def _dispatch_serve(args: list[str]) -> None:
    port = _int_opt_value("--port", 8005)
    cmd_serve(port=port)


def _dispatch_migrate(args: list[str]) -> None:
    cmd_migrate()


def _dispatch_completions(args: list[str]) -> None:
    shell = args[0] if args else "bash"
    cmd_completions(shell)


#: Commands defined on the click group in ``cli_click`` rather than in the
#: legacy ``_COMMANDS`` table. ``mcp`` MUST be here: ``pry mcp --stdio``,
#: ``pry mcp serve`` and ``pry mcp info`` live on the click group, and an
#: unlisted command falls through to ``Unknown command: mcp``.
_CLICK_COMMANDS = frozenset({"mcp", "proxy", "wallets"})


def _dispatch_click(cmd: str, args: list[str]) -> None:
    """Forward ``pry <cmd> ...`` to the click group with explicit argv.

    ``args=[...]`` is passed instead of relying on the ambient ``sys.argv``
    so the forwarded command line is exactly the dispatcher's own tail.
    ``cli`` is the click group from ``cli_click`` — never ``main`` — so this
    cannot recurse into the dispatcher.
    """
    if click is None:
        print(f"{RED}✖ click is not installed. Run: pip install click{NC}")
        sys.exit(1)
    cli.main(args=[cmd, *args], standalone_mode=False)


_COMMANDS: dict[str, Any] = {
    "open": _dispatch_open_like,
    "get": _dispatch_open_like,
    "scrape": _dispatch_open_like,
    "watch": _dispatch_watch,
    "crawl": _dispatch_crawl,
    "batch": _dispatch_batch,
    "parse": _dispatch_parse,
    "ss": _dispatch_screenshot,
    "screenshot": _dispatch_screenshot,
    "run": _dispatch_run,
    "serve": _dispatch_serve,
    "migrate": _dispatch_migrate,
    "db": _dispatch_migrate,
    "completions": _dispatch_completions,
    "autocomplete": _dispatch_completions,
}


