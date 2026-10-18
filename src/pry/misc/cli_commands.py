"""Pry CLI entry point (argv dispatch)."""

from __future__ import annotations

import sys

try:
    import click
except ImportError:  # pragma: no cover - click is a core dependency
    click = None  # type: ignore[assignment]

from pry.misc.cli_dispatch import (
    _CLICK_COMMANDS,
    _COMMANDS,
    _dispatch_click,
    _print_usage,
)
from pry.misc.cli_helpers import CYAN, NC, RED, VERSION, YELLOW
from pry.misc.cli_impl import (  # noqa: F401 - re-exported for callers/tests
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


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] in _CLICK_COMMANDS and click is not None:
        _dispatch_click(sys.argv[1], sys.argv[2:])
        return
    if len(sys.argv) < 2:
        _print_usage()
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    try:
        if cmd in ("-v", "--version", "version"):
            print(f"Pry v{VERSION}")
        elif cmd in ("-h", "--help", "help"):
            _print_usage()
        elif cmd in _CLICK_COMMANDS:
            _dispatch_click(cmd, args)
        else:
            handler = _COMMANDS.get(cmd)
            if handler is None:
                print(f"{RED}Unknown command: {cmd}{NC}")
                print(f"Run {CYAN}pry{NC} without arguments for help.")
                sys.exit(1)
            handler(args)

    except IndexError:
        print(f"{YELLOW}Missing argument for '{cmd}'{NC}")
        print(f"  {CYAN}pry {cmd} --help{NC} for usage.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{NC}")
        sys.exit(130)
