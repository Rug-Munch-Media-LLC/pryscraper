# Pry — API Errors

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry API Error Catalogue
status: canonical
owner: Rug Munch Media LLC Engineering
audience:
  - integrators
  - agents (MCP clients)
note: Every error shape the API actually emits, what triggers it, and what a client should do next.
---

# Error Catalogue

Pry does **not** use one error envelope. Four shapes are live, and a client that
assumes a single shape will misclassify failures. Branch on `Content-Type` and
`success` before branching on the status code.

| Shape | `Content-Type` | Status | Emitted by |
|-------|----------------|--------|-----------|
| RFC 7807 problem | `application/problem+json` | 4xx/5xx | `HTTPException`, `PryError`, unhandled exceptions |
| FastAPI validation | `application/json` | 422 | request body/query/path validation |
| Legacy envelope | `application/json` | **200** | scraping/OCR/proxy/webhook helpers that return a dict |
| x402 challenge | `application/json` | 402 | the x402 middleware on paid operations |

Correlation: RFC 7807 bodies carry `request_id`; quote it when escalating. Do not
parse `timestamp` for logic — it is server clock, not a retry signal.

---

## 1. RFC 7807 Problem Details

Source: `src/pry/api/exception_handlers.py` (plus `PryError.to_dict()` in
`src/pry/core/errors.py`).

```json
{
  "type": "/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Unauthorized: valid API key required (or loopback client when no key is configured)",
  "request_id": "9f2c1a7b4e01",
  "instance": "https://api.pryscraper.com/v1/proxy/configure",
  "timestamp": "2026-10-18T09:14:22.481+00:00",
  "code": "unauthorized"
}
```

| Field | Meaning |
|-------|---------|
| `type` | URI-ish category. `about:blank` for every 500 — never branch on it for 5xx |
| `title` | Short reason phrase, stable per status |
| `status` | Mirrors the HTTP status |
| `detail` | Human-readable message; for `PryError` subclasses this is the error message |
| `code` | snake_case machine key (`not_found`, `rate_limit_exceeded`, `internal_error`) |
| `request_id` | Server log correlation ID — include in bug reports |
| `instance` | Request URL that produced the error |
| `errors` | Present only when a `PryError` carries `details` |
| `verdict`, `tiers_attempted`, `tiers_failed` | Scrape failures only — says **why** the scrape failed |

**Where:** configured/protected routes (`POST /v1/proxy/configure`,
`GET /v1/config/*`), admin routes (`403` non-loopback), any `404`, any
`RateLimitError` (`429`), and every unhandled exception (`500`, `detail` is
always the generic `"An unexpected error occurred"`).

**Client action**

- `400` / `404` / `409` → **fix** the request; retrying unchanged cannot succeed.
- `401` / `403` → **fix** credentials or network origin (admin is loopback-only
  unless `PRY_ADMIN_LOOPBACK_ONLY=false`); do not retry in a loop.
- `429` → **wait**. Respect `Retry-After` when present; otherwise exponential
  backoff from 1s, cap 5 attempts.
- `500` / `502` / `503` → **retry** with jitter (2–3 attempts), then **escalate**
  with `request_id`, `instance`, and `timestamp`. Never parse `detail` for
  control flow — it is generic by design.

---

## 2. FastAPI Validation (422)

Emitted by FastAPI's default `RequestValidationError` handler, which bypasses the
RFC 7807 handler. Declared on **291 of 371** operations in `openapi.json`.

```json
{
  "detail": [
    {
      "type": "url_parsing",
      "loc": ["body", "url"],
      "msg": "Input should be a valid URL, unable to parse URL",
      "input": "not-a-url"
    }
  ]
}
```

`loc` is the JSON path to the offending field (`["body", "url"]`,
`["query", "limit"]`); `type` is the Pydantic error key; `ctx` appears on some
types only.

**Where:** every operation that takes a body, query, or typed path parameter —
`POST /v1/scrape`, `POST /v1/crawl`, `POST /v1/extract/*`, `POST /v1/x402/*`, etc.

**Client action:** **fix** — the request never reached business logic. Read `loc`
and correct that field. Retrying the same payload is guaranteed to fail again.
`422` is not a transient error and must not consume retry budget.

---

## 3. Legacy `success: false` envelope (HTTP 200)

Several routers catch their own failures and return a dict instead of raising, so
the transport status stays `200` while the payload reports failure. A client that
only checks `response.status_code` will treat these as successes.

```json
{ "success": false, "error": "thumbnail extraction failed", "data": { "thumbnail": null } }
```

Variants: `{"success": false, "error": "<300-char message>"}` (runtime failure)
and `{"success": false, "error": "Provide image_url or image_base64"}` (bad input).

**Where:** `POST /v1/thumbnail` (`extraction_thumbnail.py`),
`GET /v1/proxy/referrals/{tag}` (`core/proxy.py`), `POST /v1/webhooks/test`
(`integrations/webhooks.py`), and the advanced scraping/OCR routes in
`scraping/advanced.py` (missing dependency, unsupported input, caught exception).

**Client action**

- **Fix** when `error` names an input problem (`Provide image_url or image_base64`,
  `URL validation failed: …`, `curl_cffi not installed` — the last is a server
  deployment fault, so **escalate**, do not retry).
- **Retry** only for the generic `<exception>` message, at most twice — these
  paths catch broad exceptions and the underlying failure is usually the target
  site, not Pry.
- Treat `success` as required: `if not body.get("success")` before reading `data`.

---

## 4. x402 Payment Required (402)

Not a failure — a payment challenge. Built by
`src/pry/payments/x402/scheme/pricing/manifest.py::build_payment_required` and
returned by the middleware before the route handler runs.

```json
{
  "x402Version": 1,
  "accepts": [
    {
      "scheme": "exact",
      "network": "base",
      "maxAmountRequired": "1000",
      "resource": "/v1/scrape",
      "description": "Scrape a single URL",
      "mimeType": "application/json",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "payToAddress": "0x…"
    }
  ],
  "description": "Scrape a single URL",
  "instructions": "payment required: send 1000 … then retry this request with the PAYMENT-SIGNATURE header containing the payment_id and tx_hash.",
  "error": "payment required: send 1000 … on base",
  "networks": { "…": "…" },
  "supported_assets": ["…"]
}
```

Response headers: `PAYMENT-REQUIRED` (base64 of the same body),
`X-Payment-Required: true`, `X-Payment-Options: x402`.
`instructions` and `error` are the actionable fields; `accepts` is the menu
(`maxAmountRequired` is in **atomic units**).

**Where:** the paid operation prefixes in
`src/pry/payments/x402_middleware/config.py::PAID_ENDPOINTS` — `/v1/scrape`,
`/v1/crawl`, `/v1/extract/*`, `/v1/ultimate-scrape`, `/v1/batch`, `/v1/map`,
`/v1/capture`, `/v1/automate`, `/v1/monitor`, `/v1/pdf/extract`,
`/v1/templates/*`, `/v1/graphql`, `/v1/crypto/*`, `/v1/sports/*`, and the
`/v1/{legal,realestate,jobs,travel,attention,local,gov,ip,climate,research,events,freight,energy,food,supply,appstore,news,deals,bidding}/`
prefixes.

**Client action:** **pay**, then retry **once** with
`PAYMENT-SIGNATURE: {payment_id, tx_hash}` (or a pre-verified `X-Payment-Id`).
Prefer `POST /v1/x402/pay` to buy an access token when making several calls.
Call `GET /v1/x402/pricing` for the price table and treasuries. A second 402
after a settled payment means the signature did not bind to the operation or
caller — **escalate** with `payment_id` and `tx_hash`; do not pay twice blindly.

> `openapi.json` currently documents **0 of 371** operations with a `402`
> response. Treat the status as expected behaviour on paid routes even though it
> is absent from the spec.

---

## Retry matrix

| Status / signal | Retry | Action |
|-----------------|:-----:|--------|
| 400, 404, 409, 422 | no | fix the request |
| 401, 403 | no | fix credentials / origin |
| 402 | once, after payment | pay, then retry with `PAYMENT-SIGNATURE` |
| 429 | yes | honour `Retry-After`, then backoff |
| 500, 502, 503 | yes (2–3) | jittered backoff, then escalate with `request_id` |
| 200 + `success:false` | ≤2 | fix unless the `error` is a generic exception |
| timeout / connection reset | yes (2–3) | then escalate |
