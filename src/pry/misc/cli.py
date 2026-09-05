#!/usr/bin/env python3
"""Pry CLI — pry open any website.

Usage:
  pry open <url>           Scrape a URL to clean markdown
  pry watch <url>          Monitor a page for changes
  pry crawl <url>          Crawl multiple pages
  pry batch <file>         Batch scrape URLs from a file
  pry parse <url>          Parse a document (PDF, DOCX, image)
  pry screenshot <url>     Take a screenshot
  pry transform <data>     Convert data format
  pry run [pry.yml]        Execute jobs from pry.yml
  pry serve                Start the API server
  pry proxy ...            Manage proxy providers and signup

Thin facade: implementation lives in cli_helpers / cli_commands / cli_click.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry.misc.cli_click import cli, mcp_serve
from pry.misc.cli_commands import (
    _print_usage,
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
    main,
)
from pry.misc.cli_helpers import (
    API_DEFAULT,
    BOLD,
    CYAN,
    GREEN,
    NC,
    RED,
    VERSION,
    YELLOW,
    _api,
    _req,
    _spinner,
)

# Re-exports for backwards compatibility (tests import from pry.misc.cli).
__all__ = [
    "API_DEFAULT",
    "BOLD",
    "CYAN",
    "GREEN",
    "NC",
    "RED",
    "VERSION",
    "YELLOW",
    "_api",
    "_print_usage",
    "_req",
    "_spinner",
    "cli",
    "cmd_batch",
    "cmd_completions",
    "cmd_crawl",
    "cmd_migrate",
    "cmd_open",
    "cmd_parse",
    "cmd_run",
    "cmd_screenshot",
    "cmd_serve",
    "cmd_watch",
    "main",
    "mcp_serve",
]

if __name__ == "__main__":
    main()
