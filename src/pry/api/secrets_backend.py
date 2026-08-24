"""Pry - secret resolution with pluggable backends.

Resolves secrets from a pluggable backend. The default backend is `gopass`
(the fleet's standard secret store). `env` and `file` are also supported for
local dev and CI.

Selection order at import time (and per-call, since each call re-reads the
backend mode from the env):

  PRY_SECRET_BACKEND=gopass   # default - gopass at $GOPASS_BIN or `gopass`
  PRY_SECRET_BACKEND=env      # os.environ (12-factor)
  PRY_SECRET_BACKEND=file     # .env file in PRY_DATA_DIR/.env or PRY_ENV_FILE
  PRY_SECRET_BACKEND=auto     # try gopass, fall back to env

Usage:
    from pry.api.secrets_backend import get_secret
    api_key = get_secret("pry/openrouter_api_key")
    jwt_secret = get_secret("pry/jwt_secret", default="change-me")

The gopass lookup path is `pry/<name>`. If you pass a name with leading
"pry/" we use it as-is. If you pass "openrouter_api_key" we prepend "pry/".

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Backend constants
BACKEND_GOPASS = "gopass"
BACKEND_ENV = "env"
BACKEND_FILE = "file"
BACKEND_AUTO = "auto"
VALID_BACKENDS = {BACKEND_GOPASS, BACKEND_ENV, BACKEND_FILE, BACKEND_AUTO}

_DEFAULT_BACKEND = BACKEND_AUTO
# Where to put the .env file by default (overridable via PRY_ENV_FILE)
from pry.core.paths import PRY_DATA_DIR  # noqa: E402 - import after the docstring

_DEFAULT_ENV_FILE = PRY_DATA_DIR / ".env"

# Lazy probe results
_GOPASS_AVAILABLE: bool | None = None


def _detect_backend() -> str:
    """Resolve which backend to use right now, based on env + availability."""
    requested = os.getenv("PRY_SECRET_BACKEND", _DEFAULT_BACKEND).lower()
    if requested not in VALID_BACKENDS:
        logger.warning(
            "invalid_secret_backend", extra={"value": requested, "fallback": BACKEND_AUTO}
        )
        return BACKEND_AUTO
    if requested == BACKEND_AUTO:
        return BACKEND_GOPASS if _gopass_available() else BACKEND_ENV
    return requested


def _gopass_available() -> bool:
    """Check once whether gopass is on PATH and working."""
    global _GOPASS_AVAILABLE
    if _GOPASS_AVAILABLE is not None:
        return _GOPASS_AVAILABLE
    bin_path = shutil.which("gopass")
    if not bin_path:
        _GOPASS_AVAILABLE = False
        return False
    try:
        result = subprocess.run(
            [bin_path, "ls"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        _GOPASS_AVAILABLE = result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("gopass_probe_failed", extra={"error": str(e)[:80]})
        _GOPASS_AVAILABLE = False
    return _GOPASS_AVAILABLE


def _normalize_name(name: str) -> str:
    """Normalize a secret name to a gopass-style path under pry/."""
    if name.startswith("pry/"):
        return name
    return f"pry/{name}"


def _get_from_gopass(name: str) -> str | None:
    """Read a secret from gopass. Returns None on miss or error."""
    if not _gopass_available():
        return None
    bin_path = shutil.which("gopass")
    if not bin_path:
        return None
    path = _normalize_name(name)
    try:
        result = subprocess.run(
            [bin_path, "show", "-o", path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            value = result.stdout.rstrip("\n")
            if value:
                return value
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("gopass_read_failed", extra={"path": path, "error": str(e)[:80]})
    return None


def _get_from_env(name: str) -> str | None:
    """Read a secret from the process environment. The name is upper-cased and
    prefixed with PRY_ to match the convention used elsewhere in the codebase."""
    candidates = [
        os.getenv(name),
        os.getenv(name.upper()),
        os.getenv(f"PRY_{name.upper()}"),
        os.getenv(f"PRY_{name}"),
    ]
    for v in candidates:
        if v:
            return v
    return None


@lru_cache(maxsize=1)
def _read_env_file() -> dict[str, str]:
    """Read a .env file once. Returns dict of KEY=value pairs."""
    path = Path(os.getenv("PRY_ENV_FILE", str(_DEFAULT_ENV_FILE)))
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as e:
        logger.debug("env_file_read_failed", extra={"path": str(path), "error": str(e)[:80]})
    return values


def _get_from_file(name: str) -> str | None:
    """Read a secret from the .env file."""
    values = _read_env_file()
    for key in (name, name.upper(), f"PRY_{name.upper()}", f"PRY_{name}"):
        if values.get(key):
            return values[key]
    return None


def get_secret(name: str, default: str = "") -> str:
    """Get a secret by name, using the configured backend.

    Args:
        name: Secret name. Will be looked up as `pry/<name>` in gopass, and
            as `PRY_<NAME>` (uppercased) in env vars.
        default: Value to return if the secret isn't found in any backend.

    Returns:
        The secret string, or `default` if not found.
    """
    backend = _detect_backend()
    if backend == BACKEND_GOPASS:
        v = _get_from_gopass(name)
        if v is not None:
            return v
        # Fall through to env if gopass misses (so a partial migration works)
        v = _get_from_env(name)
        if v is not None:
            return v
    elif backend == BACKEND_ENV:
        v = _get_from_env(name)
        if v is not None:
            return v
    elif backend == BACKEND_FILE:
        v = _get_from_file(name)
        if v is not None:
            return v
    return default


def set_secret(name: str, value: str) -> bool:
    """Write a secret to gopass (the only backend that supports writes).

    Returns True on success, False on failure.
    """
    if not _gopass_available():
        logger.warning(
            "set_secret_skipped", extra={"reason": "gopass not available", "secret_name": name}
        )
        return False
    bin_path = shutil.which("gopass")
    if bin_path is None:
        logger.warning("gopass_not_found", extra={"secret_name": name})
        return False
    path = _normalize_name(name)
    try:
        result = subprocess.run(
            [bin_path, "insert", "-f", "-m", path],
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            logger.info("secret_stored", extra={"path": path})
            return True
        logger.warning("gopass_insert_failed", extra={"path": path, "stderr": result.stderr[:200]})
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("gopass_insert_error", extra={"path": path, "error": str(e)[:80]})
    return False


def backend_info() -> dict[str, str]:
    """Diagnostic info about the current backend configuration."""
    return {
        "requested": os.getenv("PRY_SECRET_BACKEND", _DEFAULT_BACKEND),
        "active": _detect_backend(),
        "gopass_available": str(_gopass_available()),
        "gopass_path": shutil.which("gopass") or "",
        "env_file": os.getenv("PRY_ENV_FILE", str(_DEFAULT_ENV_FILE)),
    }
