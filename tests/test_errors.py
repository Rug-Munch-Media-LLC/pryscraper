"""Tests for errors.py — RFC 7807 typed error hierarchy."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.core.errors import (
    ExternalServiceError,
    InvalidRequestError,
    NotFoundError,
    PryError,
    RateLimitError,
    ScrapeError,
    _code_to_type,
    _default_title,
)


def test_default_title_known():
    assert _default_title(404) == "Not Found"
    assert _default_title(500) == "Internal Server Error"
    assert _default_title(429) == "Too Many Requests"


def test_default_title_unknown():
    assert _default_title(999) == "Error"


def test_code_to_type():
    assert _code_to_type("not_found") == "/errors/not_found"
    assert _code_to_type("scrape.failed") == "/errors/scrape/failed"
    assert _code_to_type("rate.limit.exceeded") == "/errors/rate/limit/exceeded"


def test_pry_error_defaults():
    e = PryError()
    assert e.status_code == 500
    assert e.code == "internal_error"
    assert e.message == "An unexpected error occurred"
    assert e.details is None


def test_pry_error_custom_message():
    e = PryError("Custom error message", details={"field": "value"})
    assert e.message == "Custom error message"
    expected = {"field": "value"}
    assert e.details == expected


def test_pry_error_to_dict():
    e = PryError("Test error")
    d = e.to_dict(request_id="req-123", instance="/v1/scrape")
    assert d["type"] == "/errors/internal_error"
    assert d["title"] == "Internal Server Error"
    assert d["status"] == 500
    assert d["detail"] == "Test error"
    assert d["request_id"] == "req-123"
    assert d["instance"] == "/v1/scrape"
    assert "timestamp" in d


def test_pry_error_to_dict_with_details():
    e = PryError("Validation failed", details={"field": "email", "reason": "invalid"})
    d = e.to_dict()
    expected = {"field": "email", "reason": "invalid"}
    assert d["errors"] == expected
    assert "code" in d


def test_pry_error_to_dict_no_request_id():
    e = PryError("No ID")
    d = e.to_dict()
    assert "request_id" not in d
    assert "instance" not in d


def test_pry_error_is_exception():
    e = PryError("test")
    assert isinstance(e, Exception)


def test_not_found_error():
    e = NotFoundError("User not found")
    assert e.status_code == 404
    assert e.code == "not_found"
    assert e.message == "User not found"
    d = e.to_dict()
    assert d["status"] == 404
    assert d["type"] == "/errors/not_found"


def test_rate_limit_error():
    e = RateLimitError("Too fast")
    assert e.status_code == 429
    assert e.code == "rate_limit_exceeded"
    d = e.to_dict()
    assert d["status"] == 429


def test_scrape_error():
    e = ScrapeError("Could not scrape")
    assert e.status_code == 422
    assert e.code == "scrape_failed"
    d = e.to_dict()
    assert d["status"] == 422


def test_invalid_request_error():
    e = InvalidRequestError("Invalid input")
    assert e.status_code == 400
    assert e.code == "invalid_request"


def test_external_service_error():
    e = ExternalServiceError("Upstream down")
    assert e.status_code == 502
    assert e.code == "external_service_error"


def test_error_inherits_from_previous():
    """Each error type can be caught as PryError. ScrapeError takes a message."""
    errors = [
        NotFoundError(),
        RateLimitError(),
        ScrapeError("all tiers exhausted", verdict="blocked"),
        InvalidRequestError(),
        ExternalServiceError(),
    ]
    for e in errors:
        assert isinstance(e, PryError)
        assert isinstance(e, Exception)


def test_error_to_json_serializable():
    """to_dict output must be JSON-serializable."""
    e = PryError("JSON test", details={"nested": {"value": 42}})
    d = e.to_dict(request_id="r1", instance="/v1/test")
    json_str = json.dumps(d)
    assert json_str
    parsed = json.loads(json_str)
    assert parsed["detail"] == "JSON test"


def test_error_with_none_details():
    e = PryError("No details", details=None)
    d = e.to_dict()
    assert "errors" not in d


class TestErrorHandlers:
    """Integration tests: error handlers produce correct JSON responses."""

    def _make_app(self):
        a = FastAPI()

        @a.get("/test-not-found")
        async def test_not_found():
            raise NotFoundError("Resource not found")

        @a.get("/test-rate-limit")
        async def test_rate_limit():
            raise RateLimitError("Rate limited", details={"retry_after": 30})

        @a.get("/test-scrape-error")
        async def test_scrape_error():
            raise ScrapeError("Blocked by Cloudflare")

        @a.get("/test-generic")
        async def test_generic():
            raise PryError("Generic failure")

        from pry.api.api import add_error_handlers

        add_error_handlers(a)
        return a

    def test_not_found_response(self):
        c = TestClient(self._make_app())
        r = c.get("/test-not-found")
        assert r.status_code == 404
        data = r.json()
        assert data["type"] == "/errors/not_found"
        assert data["detail"] == "Resource not found"
        assert data["status"] == 404

    def test_rate_limit_response(self):
        c = TestClient(self._make_app())
        r = c.get("/test-rate-limit")
        assert r.status_code == 429
        data = r.json()
        assert data["code"] == "rate_limit_exceeded"
        expected = {"retry_after": 30}
        assert data["errors"] == expected

    def test_scrape_error_response(self):
        c = TestClient(self._make_app())
        r = c.get("/test-scrape-error")
        assert r.status_code == 422
        assert r.json()["code"] == "scrape_failed"

    def test_generic_error_response(self):
        c = TestClient(self._make_app())
        r = c.get("/test-generic")
        assert r.status_code == 500
        assert r.json()["code"] == "internal_error"

    def test_rfc7807_response_headers(self):
        c = TestClient(self._make_app())
        r = c.get("/test-not-found")
        assert r.headers.get("content-type", "").startswith("application/json")
