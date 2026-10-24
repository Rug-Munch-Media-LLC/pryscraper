"""Support helpers for the url_guard fuzz suite.

Split out so tests/fuzz/test_url_guard_fuzz.py stays within the 200-line cap
as the suite grows; the gate blocks growth on grandfathered files.
"""
from __future__ import annotations

import http.client
import socket
from urllib.parse import urlsplit  # noqa: F401  (kept for helper parity)


def _is_known_stdlib_parse_error(e: BaseException) -> bool:
    """Defensive guard for any residual stdlib parse leak.

    url_guard.py now wraps malformed-host parsing in InvalidRequestError, so
    this should never match; kept as a safety net so a future regression in
    urllib.parse behavior still fails the property test loudly instead of
    silently passing.
    """
    return isinstance(e, ValueError) and "Invalid IPv6 URL" in str(e)

def _assert_accepted_unchanged(url: str, result: str) -> None:
    """validate_url is documented to return the URL unchanged when accepted."""
    assert result == url, f"validate_url mutated accepted URL: {url!r} -> {result!r}"
