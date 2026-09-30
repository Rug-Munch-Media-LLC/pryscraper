"""OpenRouter API-key resolution for the vision router.

Split out of ``vision.py`` so the credential lookup has one owner. The route
module imports this and calls through the module attribute at call time, so
patching either module is visible to the other.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import os

from pry.core.settings import settings


def _get_or_key() -> str | None:
    """Pull OPENROUTER_API_KEY from ~/.hermes/.env or env."""
    key = settings.openrouter_api_key
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(env_path):
        return None
    with open(env_path) as f:
        for line in f:
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None
