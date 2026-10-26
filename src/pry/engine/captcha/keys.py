"""Pry — CAPTCHA solver key provisioning (file-first, env last).

Provisioning contract: write the keys into the file named by
``PRY_CAPTCHA_ENV_FILE`` (``PRY_CAPTCHA_CAPSOLVER_API_KEY=...`` /
``PRY_CAPTCHA_2CAPTCHA_API_KEY=...``).
``load_captcha_keys`` reads that file first, then the process environment, and
only fills settings fields that are still empty. A key added to the file is
picked up on the next process start with no code change.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: File-first provisioning path (override with ``PRY_CAPTCHA_ENV_FILE``).
CAPTCHA_ENV_FILE = Path(os.environ.get("PRY_CAPTCHA_ENV_FILE", "/etc/pry/captcha.env"))

#: Env var -> settings attribute for the token-solver API keys.
TOKEN_KEY_FIELDS: dict[str, str] = {
    "PRY_CAPTCHA_CAPSOLVER_API_KEY": "captcha_capsolver_api_key",
    "PRY_CAPTCHA_2CAPTCHA_API_KEY": "captcha_2captcha_api_key",
}


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` secrets file; return {} when it is absent."""
    if not path.is_file():
        return {}
    pairs: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            pairs[name.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        logger.warning("captcha_key_file_unreadable path=%s", path, exc_info=True)
        return {}
    return pairs


def load_captcha_keys() -> dict[str, bool]:
    """Populate token-solver keys from the secrets file, then the environment.

    Returns a mapping of env var name -> whether a non-empty key is now set.
    Settings fields already populated win; this never overwrites a key.
    """
    from pry.core.settings import settings

    file_values = _read_env_file(CAPTCHA_ENV_FILE)
    status: dict[str, bool] = {}
    for env_name, attr in TOKEN_KEY_FIELDS.items():
        value = file_values.get(env_name) or os.environ.get(env_name, "")
        if value and not getattr(settings, attr, ""):
            try:
                setattr(settings, attr, value)
            except (ValueError, TypeError):
                logger.warning("captcha_key_assign_failed env=%s", env_name)
        if value and not os.environ.get(env_name):
            os.environ[env_name] = value
        status[env_name] = bool(getattr(settings, attr, ""))
    return status


def missing_token_keys() -> list[str]:
    """Return the env var names of token solvers that have no key provisioned."""
    status = load_captcha_keys()
    return [name for name, present in status.items() if not present]
