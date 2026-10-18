"""SSRF and path traversal guard for Pry scrapers.

Public facade: validation lives in :mod:`~pry.engine.url_guard.url_validate`,
host/IP checks in :mod:`~pry.engine.url_guard.url_host`, and capped SSRF-safe
fetching in :mod:`~pry.engine.url_guard.url_fetch`.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from pry.engine.url_guard.url_fetch import (
    MAX_RESPONSE_BYTES,
    read_capped_body,
    safe_get,
)
from pry.engine.url_guard.url_host import _validate_host
from pry.engine.url_guard.url_validate import (
    _error,
    validate_redirect_url,
    validate_url,
    validate_url_async,
)

__all__ = [
    "MAX_RESPONSE_BYTES",
    "_error",
    "_validate_host",
    "read_capped_body",
    "safe_get",
    "validate_redirect_url",
    "validate_url",
    "validate_url_async",
]
