# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for email inbox scraping."""

import pytest

from pry.engine.email_scraper import (
    _classify_email,
    extract_email_data,
)


def test_classify_order() -> None:
    result = _classify_email("Your Amazon.com order has shipped!", "Order #123-4567890")
    assert result == "order_confirmation"


def test_classify_invoice() -> None:
    result = _classify_email("Invoice from Acme Corp", "Invoice #INV-2024-001 is due")
    assert result == "invoice"


def test_classify_receipt() -> None:
    result = _classify_email("Your receipt from Starbucks", "Receipt #12345")
    assert result == "receipt"


def test_classify_shipping() -> None:
    result = _classify_email("Your package is on its way!", "Tracking number: 1Z999AA10123456784")
    assert result == "shipping_notification"


def test_classify_other() -> None:
    result = _classify_email("Meeting reminder", "Don't forget the meeting at 3pm")
    assert result == "other"


def test_extract_order_number() -> None:
    result = extract_email_data(
        "Order Confirmation", "Order #ABC-12345 has been placed. Total: $49.99", "orders@shop.com"
    )
    assert result["email_type"] == "order_confirmation"
    assert "ABC-12345" in str(result["extracted_data"])


def test_extract_amount() -> None:
    result = extract_email_data("Receipt", "Amount charged: $129.99", "billing@store.com")
    assert result["email_type"] == "receipt"


def test_extract_tracking() -> None:
    result = extract_email_data(
        "Shipping Update", "Your tracking number is 1Z999AA10123456784", "shipping@ups.com"
    )
    assert result["email_type"] == "shipping_notification"
    assert "1Z999AA10123456784" in str(result["extracted_data"]) or "tracking" in str(
        result["extracted_data"]
    )


def test_extract_invoice_number() -> None:
    result = extract_email_data(
        "Invoice from Vendor", "Invoice #INV-2024-001 for $5,000.00", "billing@vendor.com"
    )
    assert result["email_type"] == "invoice"


# ── fetch_gmail_emails: partial fetch failures must not read clean ────
#
# The listing request and the per-message content requests are separate
# calls. When some of the per-message fetches fail, the result is a
# partial read, and a bare ``success: True`` with a short ``total`` hides
# the messages that were never retrieved.


class _FakeResponse:
    def __init__(self, is_success: bool, payload: object = None, text: str = "") -> None:
        self.is_success = is_success
        self._payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> object:
        return self._payload


class _FakeClient:
    """Client that lists N messages and fails the fetch of a chosen subset."""

    def __init__(self, message_ids: list[str], failing: set[str]) -> None:
        self.message_ids = message_ids
        self.failing = failing

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/messages"):
            return _FakeResponse(True, {"messages": [{"id": m} for m in self.message_ids]})
        msg_id = url.rsplit("/", 1)[-1]
        if msg_id in self.failing:
            return _FakeResponse(False, text=f"boom {msg_id}")
        return _FakeResponse(True, {"payload": {"headers": [], "body": {"parts": []}}})


def _patch_client(monkeypatch: object, client: _FakeClient) -> None:
    import pry.api.client as api_client

    async def _get_client() -> _FakeClient:
        return client

    monkeypatch.setattr(api_client, "get_client", _get_client)  # type: ignore[attr-defined]


async def test_fetch_gmail_emails_reports_partial_when_some_fetches_fail(monkeypatch):
    from pry.engine.email_scraper import fetch_gmail_emails

    _patch_client(monkeypatch, _FakeClient(["a", "b", "c"], failing={"b"}))

    result = await fetch_gmail_emails("token", max_results=3, query="q")

    # b's content was never retrieved — the caller must be able to see that.
    assert result["partial"] is True
    assert result["failed_count"] == 1
    assert "1 message(s) failed to fetch" in result["note"]


async def test_fetch_gmail_emails_clean_when_all_fetches_succeed(monkeypatch):
    from pry.engine.email_scraper import fetch_gmail_emails

    _patch_client(monkeypatch, _FakeClient(["a", "b"], failing=set()))

    result = await fetch_gmail_emails("token", max_results=2, query="q")

    assert result["success"] is True
    assert "partial" not in result
    assert "failed_count" not in result


# ── BYOK: Pry holds no mail credentials, so an absent token is a caller error ──
# The caller supplies their own OAuth2 token; Pry stores no refresh token and has
# no service account. A blank token used to be sent anyway, and Gmail/Graph answer
# that with an opaque 401 that reads like an auth failure rather than the caller
# bug it actually is.


@pytest.mark.parametrize("provider", ["gmail", "outlook"])
@pytest.mark.parametrize("token", ["", "   "])
async def test_missing_byok_token_is_rejected_without_a_network_call(token, provider):
    from pry.engine.email_scraper import fetch_gmail_emails, fetch_outlook_emails

    fetch = fetch_gmail_emails if provider == "gmail" else fetch_outlook_emails
    result = await fetch(token)

    assert result["success"] is False
    assert result["code"] == "missing_token"
    # The message must name the scope the caller needs, or it is not actionable.
    assert "gmail.readonly" in result["error"] or "Mail.Read" in result["error"]
    assert "BYOK" in result["error"]


async def test_byok_token_is_sent_as_a_bearer_header(monkeypatch):
    """The caller's token must reach the provider verbatim, and nothing else."""
    from pry.engine.email_scraper import fetch_gmail_emails

    seen: dict[str, str] = {}

    class _C:
        async def get(self, url, *, params=None, headers=None, timeout=None):  # noqa: ASYNC109 - mirrors the real httpx call it stubs
            seen.update(headers or {})
            return _FakeResponse(True, {"messages": []})

    import pry.api.client as api_client

    async def _get_client():
        return _C()

    monkeypatch.setattr(api_client, "get_client", _get_client)  # type: ignore[attr-defined]

    await fetch_gmail_emails("ya29.my-token")

    assert seen["Authorization"] == "Bearer ya29.my-token"
    # BYOK means no ambient credential is attached alongside the caller's.
    assert set(seen) == {"Authorization"}


async def test_outlook_fetch_is_wired_to_graph(monkeypatch):
    """Outlook had no coverage at all; this pins that it targets Graph."""
    from pry.engine.email_scraper import fetch_outlook_emails

    urls: list[str] = []

    class _C:
        async def get(self, url, *, params=None, headers=None, timeout=None):  # noqa: ASYNC109 - mirrors the real httpx call it stubs
            urls.append(url)
            return _FakeResponse(True, {"value": []})

    import pry.api.client as api_client

    async def _get_client():
        return _C()

    monkeypatch.setattr(api_client, "get_client", _get_client)  # type: ignore[attr-defined]

    result = await fetch_outlook_emails("tok")

    assert result["success"] is True
    assert any("graph.microsoft.com" in u for u in urls), urls
