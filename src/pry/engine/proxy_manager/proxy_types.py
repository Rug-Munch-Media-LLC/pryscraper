"""Proxy configuration types and credential redaction.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pry.core.paths import PRY_DATA_DIR

PROXY_DIR = PRY_DATA_DIR / "proxies"
PROXY_DIR.mkdir(parents=True, exist_ok=True)

#: Credential files are owner-only: they hold proxy user/pass and API keys.
CREDENTIALS_MODE = 0o600

_URL_USERINFO_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
_SECRET_KV_RE = re.compile(
    r"(?i)((?:password|passwd|api[_-]?key)\s*[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)


def redact_credentials(text: str) -> str:
    """Mask passwords/API keys in a URL or log/exception string.

    Defensive last line: callers must never interpolate raw config dicts into
    logs, but if one slips through this keeps the secret out of the log line.
    """
    if not text:
        return text
    masked = _URL_USERINFO_RE.sub(r"\1***\3", str(text))
    return _SECRET_KV_RE.sub(r"\1***", masked)


@dataclass
class ProxyConfig:
    """Proxy configuration.

    ``password`` and ``api_key`` are excluded from ``repr()`` so a stray
    ``logger.debug("%s", config)`` cannot leak them.
    """

    provider: str = "free"
    proxy_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    proxy_type: str = "http"
    geo: str = "auto"
    rotation: str = "per_request"
    auto_rotate: bool = True


__all__ = [
    "CREDENTIALS_MODE",
    "PROXY_DIR",
    "ProxyConfig",
    "redact_credentials",
]
