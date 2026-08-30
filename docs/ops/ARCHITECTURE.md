# Pry Architecture

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Architecture & Design
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-08-30
audience:
  - engineers
  - agents
note: Replaces Firecrawl, Crawl4AI, and Browserless in a single self-hosted application. Supersedes the prior 10-tier architecture note — the live engine is a 15-tier adaptive fallback chain (see `src/pry/engine/ultimate_scraper.py`).
---

# Pry Architecture

Pry (v3.0.0) is a self-hosted web scraping + browser automation platform
exposed simultaneously as an MCP server and a REST API, monetized per-call via
native [x402](https://docs.x402.org/) crypto micropayments. It routes every
request through an adaptive **15-tier anti-bot fallback chain**, escalated only
as far as the target requires, then remembers what worked per domain.

**Stack**: Python 3.11+/3.12, FastAPI, Playwright, FlareSolverr, Redis, Postgres,
httpx, Prometheus.

## Components

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                Pry Platform                                 │
├────────────────────────────────────────────────────────────────────────────┤
│  MCP Layer (76 tools)            │  REST API (v1, ~298 operations)          │
│  /mcp  (SSE + Streamable HTTP)   │  /v1/*  (93 router files)                │
│  /sse                            │  /.well-known/* + /llms.txt              │
├────────────────────────────────────────────────────────────────────────────┤
│  X402Middleware  ── payment gate (402 → verify → settle)                    │
│  PryHttpMiddleware ── auth, rate-limit, request-id, timing, metrics          │
│  CORS + RFC 7807 error handlers                                              │
├────────────────────────────────────────────────────────────────────────────┤
│  Scraping Engine (UltimateScraper) — 15-tier adaptive fallback               │
│  proxy_manager · captcha/* · stealth_engine · cookie_warmer · quality        │
├────────────────────────────────────────────────────────────────────────────┤
│  LLM Intelligence Layer — 18 provider classes, fallback chain, cost tracker  │
│  (registry.py + providers.py + base.py)                                      │
├────────────────────────────────────────────────────────────────────────────┤
│  Payments / x402 — facilitator router, SelfFacilitator (EIP-3009),          │
│  scheme (multi-chain accepts), solana_verifier, tron_verifier, batch         │
├────────────────────────────────────────────────────────────────────────────┤
│  Commerce / Billing — billing_service (USD ledger), packs, subscription,     │
│  enforcement tiers, signup, marketplace                                       │
└────────────────────────────────────────────────────────────────────────────┘
```

## 15-Tier Scraping Engine

`UltimateScraper.tier_order` (in `src/pry/engine/ultimate_scraper.py`) builds the
chain below, reordered per-domain by the adaptive registry
(`src/pry/engine/adaptive.py`). Each tier is wrapped in a per-domain circuit
breaker and a retry config; a block signal short-circuits to the next tier and
a success locks the tier's priority for the domain's next request.

| # | Tier | Method |
|---|------|--------|
| 1 | `direct` | Plain HTTP, rotating UA + browser-like headers |
| 2 | `tls_fingerprint` | TLS impersonation (curl-impersonate class) |
| 3 | `cloudscraper` | Python-native Cloudflare JS challenge |
| 4 | `flaresolverr` | Headless Chrome Cloudflare/WAF bypass (sidecar) |
| 5 | `undetected` | undetected-chromedriver — no automation flags |
| 6 | `camoufox` | Camoufox stealth Firefox |
| 7 | `playwright` | Full browser + human behavior (mouse, scroll, timing) |
| 8 | `googlebot` | Googlebot UA crawl mimic |
| 9 | `premium_proxy` | Residential / premium proxy via ProxyManager |
| 10 | `tor` | Anonymous routing via SOCKS5 (optional daemon) |
| 11 | `archive` | Archive.org / Wayback cached copy |
| 12 | `google_cache` | Google cached snapshot |
| 13 | `ai_visual` | AI visual scraping (vision model on a screenshot) |
| 14 | `mobile_app` | Mobile-app API scraping |
| 15 | `graphql` | GraphQL API discovery + query execution |

Auxiliary engines live alongside the scraper:
- `proxy_manager.py` (32 KB) — proxy pool, rotation, health scoring, Webshare integration.
- `captcha/` — `recaptcha_v2`, `recaptcha_v3`, `hcaptcha`, `turnstile`, `image_ocr`, `base`, `registry`, `token_api` (auto-fallback solvers).
- `stealth_scripts/*.js` — `webdriver_hide`, `canvas_noise`, `webgl_noise`, `audio_noise`, `human_mouse`, `human_type`.
- `block_detection.py`, `quality.py`, `resilience.py`, `retry.py`, `dedup.py`, `shadow_dom.py`, `lazy_load.py`, `graphql_discovery.py`, `mobile_app_scraper.py`, `ai_visual_scraper.py`.

## LLM Intelligence Layer

`src/pry/intelligence/llm/` is a provider-agnostic LLM abstraction:

- **`base.py`** — `LLMProvider` abstract interface, `LLMResponse`, `LLMError`,
  `cost_tracker` (in-memory spend), `parse_json_response`, `ReferralConfig`.
- **`providers.py`** — 18 provider classes, one per vendor: OpenAI, Anthropic,
  Google, Cohere, Mistral, OpenRouter, KiloCode, DeepSeek, Groq, Kimi, Nvidia,
  Nous, Zai (GLM), Cerebras, MiniMax, SiliconFlow, OpenCodeZen, and Ollama
  (always registered, free/private). `register_default_providers()` registers
  a provider only when its API key resolves (`settings.<provider>_api_key`).
- **`registry.py`** — `LLMRegistry` with a `fallback_chain`, per-provider retry
  with exponential backoff + jitter (`PRY_LLM_RETRY_*`), and `PRY_LLM_PROVIDER_ORDER`
  to control chain order. `complete()`, `complete_json()`, `stream_chat()`,
  `stream_json()` all walk the chain.

**Registered count.** 18 provider classes exist in `providers.py`; only those
with a key are registered, plus Ollama which is always registered. Order is
seeded by `PRY_LLM_PROVIDER_ORDER` (default
`zai,nvidia,groq,openrouter,kimi,cerebras,kilocode,deepseek` — free/cheap first,
paid deepseek as the backstop). `[REVIEW]` if the deployment's live chain length
differs from 18.

## Payments / x402

`src/pry/payments/x402/` implements the x402 v1 spec:

- **`__init__.py`** — config/resolution of payment wallets (`X402_WALLET`,
  `X402_NETWORK_WALLETS`), placeholder sentinels, address-format validators,
  offline-mode debug gate, `PAYMENT_VALIDITY_SECONDS`, per-network RPCs and
  ERC-20 token addresses.
- **`scheme.py`** — `X402_PRICING` (13 canonical ops), `SUPPORTED_NETWORKS`
  (7 chains), `SUPPORTED_ASSETS` (per-network asset table), base64 codecs,
  server attestation (`attest_payment_required`, keccak256-ecdsa-secp256k1-v1),
  price resolution + oracle.
- **`facilitator.py`** — `FacilitatorRouter` with `DEFAULT_FACILITATORS`
  (coinbase, payai, cloudflare, eip-7702) and auto-fallback.
- **`self_facilitator.py`** — EIP-3009 verify + settlement broadcast on Pry
  infra (no external facilitator / Coinbase CDP). Opt-in via
  `PRY_X402_SELF_FACILITATE=1`.
- **`handler.py`** — `X402Handler`: `verify_payment`, `settle_payment`, replay
  hardening (tx-hash idempotency), caller-binding, expiration.
- **`solana_verifier.py`** — real SPL USDC on-chain verifier (getTransaction
  jsonParsed — no Solana SDK).
- **`tron_verifier.py`** — `[REVIEW]` scaffold (structure/price/asset validation
  only; see `VERIFICATION_STATUS` in `scheme.py`).
- **`batch.py`** — batch payment helpers (`create_batch_payment`,
  `is_batch_paid`, `verify_batch_payment`).

`src/pry/payments/x402_middleware/` is the enforcement layer:
`enforcement.py` (`X402Middleware` ASGI gate), `classification.py`
(fail-closed free/paid route classifiers + `audit_route_classification`),
`config.py` (`PAID_ENDPOINTS` prefix→operation map + merged price tiers).

## Middleware / Enforcement

Middleware order in `src/pry/api/api.py` — **outermost first**. Registration
order in Starlette is last-adds-outermost, so `X402Middleware` (registered last,
line 428) is the outermost:

1. **`X402Middleware`** — the payment gate (OUTERMOST). Any request not on a free
   path and matching a paid prefix is served a 402 challenge unless a valid
   `payment_id` / `PAYMENT-SIGNATURE` / batch id is present and verified. It sits
   outside the auth layer on purpose: a keyless agent must reach the **402
   challenge before** the API-key auth layer rejects with 401. Verified payments
   set `scope["x402_verified"]`, which `request_authorized` accepts as the
   credential.
2. **`PryHttpMiddleware`** — auth (Bearer API key or rmi JWT), per-key/per-IP
   rate limiting, request-id, timing, Prometheus metrics.
3. **`CORSMiddleware`** — allow-list locked to `pryscraper.com` + `rugmunch.io`
   (regex) and localhost dev origins. No `*`.
4. **FastAPI routers** — the application handlers.

RFC 7807 Problem Details are emitted by the error handlers for 400/401/403/404/
409/429/500/502/503; `PryError` is translated to its own problem+json body.

## Commerce / Billing

`src/pry/commerce/`:

- **`billing_service.py`** — the machine-facing **USD ledger**: `credit`,
  `drawdown`, `get_balance`, `ledger`, `_apply`. Every pack/subscription
  purchase and every x402 settle lands here.
- **`billing/packs.py`** — bulk **scrape-credit packs** (crypto checkout via
  x402 self-facilitation). `credits * SCRAPE_CREDIT_USD == price_usd`.
  Fail-closed on unconfigured wallet.
- **`billing/subscription.py`** — monthly **Pro/Team/Enterprise** crypto
  subscriptions (x402 default, BTCPay fallback when `PRY_BTCPAY_*` set).
- **`billing/tiers.py`** — `TIERS` table (`free`/`pro`/`team`/`enterprise`):
  monthly price, request quota, concurrent limit, feature flags, rpm cap.
- **`billing/enforcer.py`** — enforces tier limits at request time.
- **`signup/`** — auto-signup automation (form detection, engine, email verify).
- **`marketplace/`** — Amazon/Walmart/TikTok/retail marketplace intelligence.
- **`referrals/`, `agency.py`, `actor_marketplace.py`, `pipelines.py`** — referral
  program, white-label agency, Actor marketplace, data pipelines.
- **`costing.py`** — per-operation cost tracking and analytics.

## REST API Surface

Composition root `src/pry/api/api.py` mounts every router (93 router files) and
the MCP sub-app. The `openapi.json` is generated at build; the live route count
is ~293 paths / **~298 operations** across ~117 path group prefixes
(`grep`-verified against `src/pry/api/routers/**`). Routers are grouped under
`core/`, `scraping/`, `data/`, `ai/`, `commerce/`, `integrations/`, `user/`,
and `well-known/`.

## MCP Server

`src/pry/api/api.py` mounts `create_mcp_app()` at `/mcp`:
- `/mcp` — Streamable HTTP transport.
- `/mcp/sse` — SSE transport.
- `/mcp/messages` — messages prefix (classified free in the gate).
- `/sse` — standalone SSE entry.
- stdio via `pry mcp serve` / `pry-mcp` / `pryscraper-mcp`.

`register_all()` binds all 76 `PRY_TOOLS`; `combined_tool_executor` runs
crypto/marketplace/data-domain tools locally and falls through to the REST proxy
for the rest. `src/pry/api/registry_metadata.py` enriches each tool with
category, keywords, use_cases, longDescription, group, and capabilities.

## Data Flow (ASCII)

```
                       ┌───────────────────────────────────┐
   Client ────────────▶│  X402Middleware (payment gate)     │  ← OUTERMOST
   (MCP / REST / CLI)  │  free? ─▶ yes → pass through       │
                       │  paid?  ─▶ 402 challenge           │
                       │          └─ verify+settle → allow   │
                       └───────────────────────────────────┘
                                    │
                                    ▼
                       ┌───────────────────────────────────┐
                       │  PryHttpMiddleware (auth/rate)     │
                       └───────────────────────────────────┘
                                    │
                                    ▼
                       ┌───────────────────────────────────┐
                       │  CORS → FastAPI routers/handlers    │
                       └───────────────┬───────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
   │  UltimateScraper   │   │  LLM Registry      │   │  Billing / Ledger  │
   │  15-tier chain     │   │  provider fallback │   │  USD prepaid       │
   │  → extraction      │   │  complete_json     │   │  credit/drawdown   │
   │  → quality         │   │  cost_tracker      │   │  subscription      │
   └────────────────────┘   └────────────────────┘   └────────────────────┘
              │                        │                        │
              ▼                        ▼                        ▼
     ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
     │ Cache / Redis    │    │ Qdrant / DB      │    │ x402 Facilitator │
     │ (rate, content)  │    │ (results, keys)  │    │ verify + settle  │
     └──────────────────┘    └──────────────────┘    └──────────────────┘
```

## Storage

Data lives under `PRY_DATA_DIR` (default `~/.pry`):

| Location | Purpose |
|----------|---------|
| `x402/` | Payment records, settlements JSONL, nonce/replay store |
| `llm_usage/` | Per-provider LLM usage + spend (registry.py) |
| `quality/`, `reviews/`, `intel/`, `costing/`, `freshness/`, `structure/`, `seo/`, `monitors/`, `vault/`, `accounts/`, `reports/`, `training/`, `pipelines/`, `gdpr/`, `agency/` | Engine/app state (docs/ops/ARCHITECTURE.md legacy tree still applies) |
| `warmed_cookies/` | Pre-warmed cookie jars for stealth |
| database (`PRY_DATABASE_URL`) | SQLite (dev) / Postgres (prod) for durable app state |

## External Dependencies

| Dependency | Purpose |
|------------|---------|
| FlareSolverr | Cloudflare/WAF challenge bypass (Docker sidecar) |
| Redis | Optional shared cache + rate limiting |
| Postgres | Durable database (default in prod) |
| Playwright (Chromium) | Full browser automation |
| Tor | Anonymous routing (optional) |
| x402 facilitator | External `coinbase`/`payai`/`cloudflare` verify+settle, OR self-facilitate |
| LLM providers | 18 provider families for AI extraction/scrape (free-first) |
