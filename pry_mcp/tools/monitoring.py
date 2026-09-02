"""Pry - MCP tool definitions: scheduled-monitor tool..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_monitor",
        "description": (
            "Create a content-change monitor that notifies via webhook, Slack, or Discord when "
            "a page changes, using AI to judge whether changes are meaningful. "
            "Use to track competitor pricing or product availability over time, e.g. "
            "'notify me when this price page changes'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable monitor name, e.g. 'Competitor pricing watch'",
                },
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The page to monitor for changes, e.g. https://example.com/pricing",
                },
                "schedule_cron": {
                    "type": "string",
                    "default": "0 */6 * * *",
                    "description": "Cron expression (default: every 6 hours)",
                },
                "webhook_url": {
                    "type": "string",
                    "format": "uri",
                    "description": "Webhook/Slack/Discord URL to notify on meaningful changes",
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "Natural language goal for AI change judging (e.g., 'price changes "
                        "matter, not descriptions')"
                    ),
                },
            },
            "required": ["name", "url"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "monitor_id": {"type": "string"},
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "schedule_cron": {"type": "string"},
                        "webhook_url": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
                "error": {"type": "string"},
            },
            "required": ["success"],
        },
    }
]
