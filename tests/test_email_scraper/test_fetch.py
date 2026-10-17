# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""fetch_gmail_emails / fetch_outlook_emails behavior."""

from __future__ import annotations

import pytest

from .conftest import _FakeClient, _FakeResponse


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
    expected = {"Authorization"}
    assert set(seen) == expected


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
