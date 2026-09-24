"""Capability report orchestration."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pry.api.capabilities.runtime import (
    _anti_bot_capability,
    _browser_capability,
    _tor_capability,
)
from pry.api.capabilities.services import (
    _captcha_capability,
    _llm_capability,
    _proxy_capability,
)
from pry.api.capabilities.storage import _storage_capability


def detect_capabilities() -> dict[str, Any]:
    """Return a structured report of what this deployment actually supports.

    Every entry is ``{"available": bool, "detail": str}``; the report also
    carries a ``recommendations`` list of actionable strings (no secrets).
    """
    sections: dict[str, Any] = {}
    recommendations: list[str] = []
    for name, detector in (
        ("browsers", _browser_capability),
        ("anti_bot", _anti_bot_capability),
        ("tor", _tor_capability),
        ("proxies", _proxy_capability),
        ("captcha", _captcha_capability),
        ("llm", _llm_capability),
        ("storage", _storage_capability),
    ):
        available, detail, recs = detector()
        sections[name] = {"available": available, "detail": detail}
        recommendations.extend(recs)

    sections["recommendations"] = recommendations
    return sections
