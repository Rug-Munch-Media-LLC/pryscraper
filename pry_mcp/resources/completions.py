"""Pry - MCP argument completion.

Completion is advisory: a broken registry must not look like "no suggestions",
so a failed lookup is logged at warning before it degrades to an empty list.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# A completion lookup may fail on an import (registry module absent) or on the
# registry's own shape (AttributeError/KeyError/TypeError/ValueError). Those
# are the failures worth reporting; anything else is a Pry bug.
COMPLETION_ERRORS = (ImportError, AttributeError, KeyError, TypeError, ValueError, RuntimeError)


def _template_ids(arg_value: str) -> list[str]:
    """Up to ten template ids matching ``arg_value`` (case-insensitive)."""
    try:
        from pry.commerce.template_engine import list_templates

        return [
            t["template_id"]
            for t in list_templates()
            if arg_value.lower() in t["template_id"].lower()
        ][:10]
    except COMPLETION_ERRORS as e:
        # An empty list is indistinguishable from "no matching template" at the
        # protocol level, so the failure is logged rather than reported as a
        # working autocomplete with no matches.
        logger.warning(
            "mcp_completion_template_id_failed",
            extra={
                "arg_value": arg_value,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return []


def completion_values(ref: dict[str, Any], argument: dict[str, Any]) -> list[str]:
    """Suggested values for one prompt/tool argument."""
    ref_type = ref.get("type", "")
    arg_name = argument.get("name", "")
    arg_value = argument.get("value", "")
    if (
        ref_type == "ref/prompt"
        and ref.get("name") == "extract_contacts"
        and arg_name == "max_pages"
    ):
        return ["10", "20", "50", "100"]
    if ref_type == "ref/tool" and arg_name == "template_id":
        return _template_ids(arg_value)
    if arg_name in ("format", "mime_type"):
        return ["json", "csv", "markdown", "html"]
    return []
