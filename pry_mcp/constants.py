"""Pry - MCP server constants."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os

# MCP protocol version (per the official spec)
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pry"
SERVER_VERSION = "3.0.0"

DEFAULT_BASE_URL = os.getenv("PRY_API_URL", "http://localhost:8002")
