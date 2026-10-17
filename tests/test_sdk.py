# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for Pry SDK classes."""

import httpx
import pytest

from pry.api.pry_sdk import PaymentRequired, PryCrawl, PryCrawlSync, PryError


def test_prycrawl_init() -> None:
    mc = PryCrawl("http://localhost:8002")
    assert mc.base_url == "http://localhost:8002"
    assert mc.timeout == 60


def test_prycrawl_init_with_key() -> None:
    mc = PryCrawl("http://localhost:8002", api_key="test-key")
    assert mc._headers["Authorization"] == "Bearer test-key"


def test_prycrawl_init_strips_trailing_slash() -> None:
    mc = PryCrawl("http://localhost:8002/")
    assert mc.base_url == "http://localhost:8002"


def test_prycrawlsync_init() -> None:
    mc = PryCrawlSync("http://localhost:8002")
    assert mc._client.base_url == "http://localhost:8002"


def test_prycrawlsync_init_with_key() -> None:
    mc = PryCrawlSync("http://localhost:8002", api_key="test-key")
    assert mc._client._headers["Authorization"] == "Bearer test-key"


async def test_prycrawl_health_returns_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    expected = {"status": "ok"}
    assert await _client(handler).health() == expected


# --- 402 / x402 flow -------------------------------------------------------

CHALLENGE = {
    "x402Version": 1,
    "accepts": [
        {
            "scheme": "exact",
            "network": "base",
            "asset": "0xUSDC",
            "payTo": "0xPAYEE",
            "maxAmountRequired": "1000000",  # 1.00 USDC at 6 decimals
            "extra": {"decimals": 6},
        }
    ],
    "resource": "/v1/scrape",
}


def _client(handler, **kw):
    return PryCrawl("http://pry.test", transport=httpx.MockTransport(handler), **kw)


async def test_402_challenge_parsed_and_retried_with_x_payment() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(402, json=CHALLENGE)
        return httpx.Response(200, json={"success": True, "url": "https://example.com"})

    payments: list[dict] = []

    def pay(challenge: dict) -> str:
        payments.append(challenge)
        return "signed-payment"

    result = await _client(handler).scrape("https://example.com", pay=pay)
    expected = {"success": True, "url": "https://example.com"}
    assert result == expected
    assert len(seen) == 2
    assert seen[1].headers["X-PAYMENT"] == "signed-payment"
    assert seen[1].headers["PAYMENT-SIGNATURE"] == "signed-payment"
    assert payments[0]["accepts"][0]["network"] == "base"
    assert payments[0]["amount_usd"] == 1.0


async def test_default_pay_raises_payment_required_with_challenge() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json=CHALLENGE)

    with pytest.raises(PaymentRequired) as excinfo:
        await _client(handler).scrape("https://example.com")
    assert excinfo.value.status == 402
    assert excinfo.value.code == "payment_required"
    assert excinfo.value.challenge["amount_usd"] == 1.0
    assert excinfo.value.challenge["pay_to"] == "0xPAYEE"


async def test_max_price_usd_exceeded_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json=CHALLENGE)

    with pytest.raises(PaymentRequired) as excinfo:
        await _client(handler, max_price_usd=0.5).scrape("https://example.com")
    assert "max" in excinfo.value.detail


# --- error model -----------------------------------------------------------


async def test_pry_error_carries_code_and_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"type": "invalid_request", "code": "bad_url", "detail": "url is required"},
        )

    with pytest.raises(PryError) as excinfo:
        await _client(handler).scrape("nope")
    assert excinfo.value.status == 400
    assert excinfo.value.code == "bad_url"
    assert excinfo.value.detail == "url is required"
    assert excinfo.value.body["type"] == "invalid_request"


# --- retries ---------------------------------------------------------------


async def test_retry_on_503_for_get_only() -> None:
    get_calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        get_calls.append(1)
        if len(get_calls) == 1:
            return httpx.Response(503, json={"detail": "warming up"})
        return httpx.Response(200, json={"status": "ok"})

    assert (await _client(handler).health())["status"] == "ok"


async def test_no_retry_for_post_on_503() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"code": "unavailable", "detail": "try later"})

    with pytest.raises(PryError) as excinfo:
        await _client(handler).scrape("https://example.com")
    assert excinfo.value.status == 503
    assert len(calls) == 1


async def test_no_retry_on_400() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"code": "bad_request", "detail": "no"})

    with pytest.raises(PryError):
        await _client(handler).scrape("https://example.com")
    assert len(calls) == 1


# --- pagination ------------------------------------------------------------


async def test_iter_pages_follows_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(200, json={"data": [3], "next_cursor": None})
        return httpx.Response(200, json={"data": [1, 2], "next_cursor": "c2"})

    pages = [item async for item in _client(handler).iter_pages("/v1/templates")]
    expected = [1, 2, 3]
    assert pages == expected
