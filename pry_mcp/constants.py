"""Pry - MCP server constants."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os

# MCP protocol ceiling. Source of truth: official spec (latest 2026-07-28).
# Never hardcode this string elsewhere — import the constant.
MCP_PROTOCOL_VERSION = "2026-07-28"

# Revisions this server can speak. The installed Python SDK may lag the spec,
# so a client that asks for an older supported revision is answered with that
# revision; anything unknown gets the ceiling.
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2026-07-28",
)


def negotiate_protocol_version(requested: str | None) -> str:
    """Return the revision to advertise for a client's ``initialize`` request."""
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return MCP_PROTOCOL_VERSION
SERVER_NAME = "pry"
SERVER_VERSION = "3.0.0"

DEFAULT_BASE_URL = os.getenv("PRY_API_URL", "http://localhost:8002")
