"""Pry - MCP tool definitions: browser actions (Firecrawl-style interactions).

Defines the ``pry_scrape_with_actions`` tool: scrape a page after performing
a sequence of browser actions (click, scroll, type, wait, press, ...) before
extracting content. The execution engine lives in
``pry.engine.actions``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

# JSON Schema for a single action object in the actions array.
_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "A single browser action. Supported types: click, type, scroll, wait, "
        "press, screenshot, evaluate, select, check, uncheck, hover, focus."
    ),
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "click",
                "type",
                "scroll",
                "wait",
                "press",
                "screenshot",
                "evaluate",
                "select",
                "check",
                "uncheck",
                "hover",
                "focus",
            ],
            "description": "The action to perform",
        },
        "selector": {
            "type": "string",
            "description": (
                "CSS selector of the target element (required for click, type, "
                "select, check, uncheck, hover, focus; optional for wait)"
            ),
        },
        "text": {
            "type": "string",
            "description": "Text to type into the input (required for type)",
        },
        "direction": {
            "type": "string",
            "enum": ["up", "down"],
            "default": "down",
            "description": "Scroll direction (for scroll)",
        },
        "amount": {
            "type": "integer",
            "default": 500,
            "description": "Scroll amount in pixels (for scroll)",
        },
        "ms": {
            "type": "integer",
            "description": "Milliseconds to wait (for wait without selector)",
        },
        "key": {
            "type": "string",
            "description": "Keyboard key to press, e.g. 'Enter', 'Tab' (for press)",
        },
        "script": {
            "type": "string",
            "description": "JavaScript to evaluate in the page (for evaluate)",
        },
        "value": {
            "type": "string",
            "description": "Option value to select (for select)",
        },
    },
    "required": ["type"],
}

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_scrape_with_actions",
        "description": (
            "Scrape a page after performing browser actions before extraction — "
            "Firecrawl-style interactions for dynamic pages. Specify a sequence of "
            "actions (click elements, type text into inputs, scroll, wait for "
            "elements or fixed delays, press keys, run JavaScript, select dropdown "
            "options, check/uncheck checkboxes, hover, focus) that are executed in "
            "order on the loaded page, then the page content is extracted. "
            "Use when a plain scrape cannot reach the content: dismissing cookie "
            "banners, logging in or submitting search forms, infinite-scroll "
            "loading, expanding collapsed sections, or paginating before capture. "
            "Example: [{type: 'click', selector: '#cookie-accept'}, "
            "{type: 'wait', ms: 1000}, {type: 'scroll', direction: 'down', "
            "amount: 2000}, {type: 'wait', selector: '.results'}]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "format": "uri",
                    "description": "The URL to load before running actions, e.g. https://example.com/login",
                },
                "actions": {
                    "type": "array",
                    "items": _ACTION_SCHEMA,
                    "maxItems": 50,
                    "description": (
                        "Ordered list of browser actions to execute before extraction. "
                        "Each action is {type, ...params}; see the type enum for the "
                        "supported set. Failed actions are skipped, not fatal."
                    ),
                },
                "extract": {
                    "type": "boolean",
                    "default": True,
                    "description": "Extract page content after all actions complete (default: true)",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "html", "text"],
                    "default": "markdown",
                    "description": "Output format for the extracted content (default: markdown)",
                },
            },
            "required": ["url", "actions"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "actions_executed": {
                            "type": "integer",
                            "description": "Number of actions that completed successfully",
                        },
                        "content": {
                            "type": "string",
                            "description": "Extracted page content in the requested format",
                        },
                        "title": {"type": "string"},
                        "screenshot": {
                            "type": "string",
                            "description": "Base64-encoded full-page screenshot (when a screenshot action ran)",
                        },
                    },
                    "required": ["url", "actions_executed"],
                },
            },
            "required": ["success"],
        },
    },
]
