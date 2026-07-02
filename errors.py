"""Pry — typed error hierarchy.
Every API error flows through here for consistent JSON responses."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any


class PryError(Exception):
    """Base error for all Pry exceptions."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred"
    details: dict[str, Any] | None = None

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            d["details"] = self.details
        return d


class NotFoundError(PryError):
    status_code = 404
    code = "not_found"


class RateLimitError(PryError):
    status_code = 429
    code = "rate_limit_exceeded"


class ScrapeError(PryError):
    status_code = 422
    code = "scrape_failed"


class InvalidRequestError(PryError):
    status_code = 400
    code = "invalid_request"


class ExternalServiceError(PryError):
    status_code = 502
    code = "external_service_error"
