"""Pry — HTML -> lxml root, degrading to None instead of raising."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any


def _to_root(html: str) -> Any | None:
    """Parse HTML into an lxml root, or None (never raises)."""
    try:
        from lxml import html as lxml_html

        return lxml_html.fromstring(html)
    except (AttributeError, TypeError, ValueError, ImportError):
        return None
