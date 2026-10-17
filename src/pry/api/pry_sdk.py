"""Pry Python SDK — typed errors, x402 payment, retries, pagination."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8005"
_CURSOR_KEYS = ("next_cursor", "nextCursor", "cursor", "next")
_ITEM_KEYS = ("data", "items", "results", "records")
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_LOOP: asyncio.AbstractEventLoop | None = None
PayCallback = Callable[[dict[str, Any]], "str | dict[str, Any] | Awaitable[Any]"]


class PryError(Exception):
    """Typed API error parsed from an RFC-7807 problem body."""

    def __init__(self, status: int, code: str = "", detail: str = "", body: Any = None) -> None:
        self.status, self.code, self.detail, self.body = status, code, detail, body
        super().__init__(f"{status} {code or 'error'}: {detail}".rstrip(": "))


class PaymentRequired(PryError):
    """HTTP 402 plus the parsed x402 challenge (``accepts[]``, network, amount)."""

    def __init__(self, challenge: dict[str, Any], reason: str = "payment required") -> None:
        self.challenge = challenge
        super().__init__(402, "payment_required", reason, challenge)


def _option_usd(accept: dict[str, Any]) -> float:
    """USD price of one x402 ``accepts`` entry (6 decimals default = USDC)."""
    if accept.get("amount_usd") is not None or accept.get("price_usd") is not None:
        return float(accept.get("amount_usd") or accept.get("price_usd") or 0)
    try:
        decimals = int((accept.get("extra") or {}).get("decimals", 6))
        return int(accept.get("maxAmountRequired", 0)) / 10**decimals
    except (TypeError, ValueError):
        return 0.0


def parse_challenge(resp: httpx.Response) -> dict[str, Any]:
    """Flatten a 402 x402 challenge body into a pay-ready dict."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    accepts = [a for a in body.get("accepts") or [] if isinstance(a, dict)]
    best = accepts[0] if accepts else {}
    return {
        "x402Version": body.get("x402Version", 1),
        "accepts": accepts,
        "scheme": best.get("scheme", ""),
        "network": best.get("network", ""),
        "asset": best.get("asset", ""),
        "pay_to": best.get("payTo") or best.get("pay_to", ""),
        "max_amount_atomic": str(best.get("maxAmountRequired", "")),
        "amount_usd": _option_usd(best),
        "resource": body.get("resource", ""),
        "raw": body,
    }


def _problem(resp: httpx.Response) -> PryError:
    try:
        body: Any = resp.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    code = body.get("code") or body.get("type") or body.get("error") or ""
    detail = body.get("detail") or body.get("title") or body.get("message") or resp.text[:300]
    return PryError(resp.status_code, str(code), str(detail), body)


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Running loop, or a persistent one for synchronous callers."""
    global _LOOP
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            asyncio.set_event_loop(_LOOP)
        return _LOOP


def _raise_payment_required(challenge: dict[str, Any]) -> str:
    raise PaymentRequired(challenge)


class PryCrawl:
    """Async Python SDK for the Pry API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: float = 60,
        max_retries: int = 2,
        max_price_usd: float | None = None,
        pay: PayCallback | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.max_retries, self.max_price_usd = max(0, int(max_retries)), max_price_usd
        self.pay, self._transport = pay or _raise_payment_required, transport
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _guard_price(self, challenge: dict[str, Any]) -> None:
        """Reject a challenge whose every option exceeds ``max_price_usd``."""
        if self.max_price_usd is None:
            return
        price = challenge["amount_usd"]
        affordable = [a for a in challenge["accepts"] if _option_usd(a) <= self.max_price_usd]
        if not affordable:
            raise PaymentRequired(challenge, f"price ${price} > max ${self.max_price_usd}")
        challenge["accepts"] = affordable

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotent: bool = False,
    ) -> httpx.Response:
        """One request; idempotent calls retry 429/5xx with exponential backoff."""
        merged = {**self._headers, **(headers or {})}
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=merged, transport=self._transport
        ) as client:
            for attempt in range(self.max_retries + 1):
                last = attempt == self.max_retries
                try:
                    resp = await client.request(
                        method, f"{self.base_url}{path}", json=json_body, params=params
                    )
                except httpx.TransportError:
                    if not idempotent or last:
                        raise
                else:
                    if not (idempotent and resp.status_code in _RETRY_STATUS) or last:
                        return resp
                await asyncio.sleep(min(0.05 * 2**attempt, 2.0))
        raise PryError(0, "transport_error", f"{method} {path} failed")

    async def _post(
        self, path: str, data: dict[str, Any], pay: PayCallback | None = None
    ) -> dict[str, Any]:
        """POST; a 402 buys exactly one paid retry through ``pay``."""
        resp = await self._send("POST", path, json_body=data)
        if resp.status_code == 402:
            challenge = parse_challenge(resp)
            self._guard_price(challenge)
            payment = (pay or self.pay)(challenge)
            if asyncio.iscoroutine(payment):
                payment = await payment
            value = (
                payment
                if isinstance(payment, str)
                else base64.b64encode(json.dumps(payment).encode()).decode()
            )
            # X-PAYMENT is the x402-standard header; Pry's gate reads PAYMENT-SIGNATURE.
            resp = await self._send(
                "POST",
                path,
                json_body=data,
                headers={"X-PAYMENT": value, "PAYMENT-SIGNATURE": value},
            )
        if resp.status_code >= 400:
            raise _problem(resp)
        return dict(resp.json())

    async def scrape(self, url: str, *, pay: PayCallback | None = None, **o: Any) -> dict[str, Any]:
        """Scrape one URL; ``pay`` overrides the client-level callback for this call."""
        return await self._post("/v1/scrape", {"url": url, **o}, pay)

    async def scrape_json(self, url: str, schema: dict[str, str], **o: Any) -> dict[str, Any]:
        return await self._post(
            "/v1/scrape", {"url": url, "formats": ["json"], "jsonSchema": schema, **o}
        )

    async def crawl(self, url: str, max_pages: int = 10, **o: Any) -> dict[str, Any]:
        return await self._post("/v1/crawl", {"url": url, "maxPages": max_pages, **o})

    async def map(self, url: str, limit: int = 50) -> dict[str, Any]:
        return await self._post("/v1/map", {"url": url, "limit": limit})

    async def parse(self, url: str) -> dict[str, Any]:
        return await self._post("/v1/parse", {"url": url})

    async def automate(self, steps: list[dict[str, Any]], **o: Any) -> dict[str, Any]:
        return await self._post("/v1/automate", {"steps": steps, **o})

    async def screenshot(self, url: str) -> dict[str, Any]:
        return await self._post("/v1/screenshot", {"url": url})

    async def health(self) -> dict[str, Any]:
        resp = await self._send("GET", "/health", idempotent=True)
        if resp.status_code >= 400:
            raise _problem(resp)
        return dict(resp.json())

    async def iter_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int = 100,
        max_pages: int = 50,
    ) -> AsyncIterator[Any]:
        """Iterate a list endpoint, following ``cursor``/``next_cursor`` when present."""
        cursor: Any = None
        for _ in range(max_pages):
            query = {**(params or {}), "limit": limit, **({"cursor": cursor} if cursor else {})}
            resp = await self._send("GET", path, params=query, idempotent=True)
            if resp.status_code >= 400:
                raise _problem(resp)
            body = resp.json()
            items = (
                body
                if isinstance(body, list)
                else next((body[k] for k in _ITEM_KEYS if isinstance(body.get(k), list)), [])
            )
            for item in items:
                yield item
            if isinstance(body, list):
                return
            cursor = next((body[k] for k in _CURSOR_KEYS if body.get(k)), None)
            if not cursor:
                return


class PryCrawlSync:
    """Synchronous wrapper — each call runs on a private event loop."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._client = PryCrawl(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            coro = getattr(self._client, name)(*args, **kwargs)
            return _get_or_create_loop().run_until_complete(coro)

        return call
