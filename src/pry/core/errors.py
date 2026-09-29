"""Pry — typed error hierarchy with RFC 7807 / RFC 9457 Problem Details.

Every API error flows through here for consistent JSON error responses
following the RFC 7807 Problem Details standard::

    {
        "type": "/errors/not_found",
        "title": "Not Found",
        "status": 404,
        "detail": "Resource not found",
        "instance": "/v1/scrape/123",
        "request_id": "abc123",
        "timestamp": "2026-07-24T..."
    }
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def _default_title(status: int) -> str:
    return _STATUS_TITLES.get(status, "Error")


def _code_to_type(code: str) -> str:
    """Convert dot-notation error code to URI path."""
    return f"/errors/{code.replace('.', '/')}"


class PryError(Exception):
    """Base error for all Pry exceptions — RFC 7807 Problem Details."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred"
    details: dict[str, Any] | None = None

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_dict(self, request_id: str = "", instance: str = "") -> dict[str, Any]:
        """Return RFC 7807 Problem Details dict.

        Security: This method only exposes the error message, code, status,
        and optional details/request_id/instance. No stack traces, internal
        paths, or exception internals are leaked. Safe for client responses.

        Args:
            request_id: Correlation ID for tracing.
            instance: URI of the request that triggered the error.
        """
        d: dict[str, Any] = {
            "type": _code_to_type(self.code),
            "title": _default_title(self.status_code),
            "status": self.status_code,
            "detail": self.message,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # A caller that cannot tell "the site refused us" from "we ran out of
        # time" retries the wrong thing, and the tier list is too noisy to infer
        # from (it is rate-limited and varies run to run). The verdict is the
        # actionable field; the tier lists are the evidence behind it.
        verdict = getattr(self, "verdict", None)
        if verdict:
            d["verdict"] = verdict
        attempted = getattr(self, "tiers_attempted", None)
        if attempted:
            d["tiers_attempted"] = list(attempted)
        failed = getattr(self, "tiers_failed", None)
        if failed:
            d["tiers_failed"] = list(failed)
        if request_id:
            d["request_id"] = request_id
        if instance:
            d["instance"] = instance
        if self.details:
            d["errors"] = self.details
        if self.code:
            d["code"] = self.code
        return d


class NotFoundError(PryError):
    status_code = 404
    code = "not_found"


class RateLimitError(PryError):
    status_code = 429
    code = "rate_limit_exceeded"


class ScrapeError(PryError):
    """A scrape failed.

    Carries the VERDICT as structured context, not just a message. The verdict
    is what a caller actually needs — "the site refused us" and "we ran out of
    time" call for different responses, and both used to arrive as an
    indistinguishable semicolon-joined bag of tier names.
    """

    status_code = 422
    code = "scrape_failed"

    def __init__(
        self,
        message: str,
        *,
        verdict: str | None = None,
        tiers_attempted: list[str] | None = None,
        tiers_failed: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.tiers_attempted = tiers_attempted or []
        self.tiers_failed = tiers_failed or []


class InvalidRequestError(PryError):
    status_code = 400
    code = "invalid_request"


class ExternalServiceError(PryError):
    status_code = 502
    code = "external_service_error"
