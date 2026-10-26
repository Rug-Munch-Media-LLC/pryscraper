"""One envelope shape for every X (Twitter) adapter, success or refusal.

Callers must never have to guess whether a payload is real data or a login
wall: ``ok`` is the only success signal, and every failure carries a stable
``error.code`` from the table below.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1

REFUSALS: dict[str, str] = {
    "blocked.auth": "surface requires an authenticated session; pry never logs in",
    "blocked.tos": "surface is out of scope (authenticated GraphQL, user cookies)",
    "blocked.ratelimit": "upstream rate-limited us (429 or an empty soft-block body)",
    "blocked.challenge": "challenge / JS-only shell with no data",
    "no_data": "response well-formed but contained no tweet objects",
}


def envelope(
    *,
    ok: bool,
    source: str,
    data: Any = None,
    code: str | None = None,
    detail: str | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    """Build the envelope returned by every ``x_*`` adapter."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "source": source,
        "data": data,
        "error": None if ok else {"code": code, "detail": detail or REFUSALS.get(code or "", "")},
        "http_status": http_status,
        "fetched_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }


def refusal(
    source: str, code: str, *, http_status: int | None = None, detail: str | None = None
) -> dict[str, Any]:
    """Shorthand for the failure branch."""
    return envelope(ok=False, source=source, code=code, detail=detail, http_status=http_status)
