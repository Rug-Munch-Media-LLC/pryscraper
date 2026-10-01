# Pry Architecture

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Architecture & Design
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-09-02
audience: [engineers, agents]
note: Replaces Firecrawl, Crawl4AI, and Browserless in one self-hosted app. Live engine is a 15-tier adaptive fallback chain (see `src/pry/engine/ultimate_scraper.py`). See DECISIONS.md for ADRs.
---

# Pry Architecture

Pry (v3.0.0) is a self-hosted web scraping + browser automation platform exposed
simultaneously as an MCP server and a REST API, monetized per-call via native
[x402](https://docs.x402.org/) crypto micropayments. It routes every request
through an adaptive **15-tier anti-bot fallback chain**, escalated only as far
as the target requires, then remembers what worked per domain.

**Stack**: Python 3.11+/3.12, FastAPI, Playwright, Camoufox,
undetected-chromedriver, FlareSolverr, Redis, Postgres, httpx, Prometheus,
OpenTelemetry + Jaeger.

## Components

- **MCP Layer (113 tools)** — `/mcp` (SSE + Streamable HTTP), `/mcp/messages`
  (auth-gated), `/sse`, stdio (`pry mcp serve`).
- **REST API (v1, ~298 operations)** — `/v1/*` (93 router files),
  `/.well-known/*` + `/llms.txt`.
- **Middleware** — `X402Middleware` (payment gate, outermost) →
  `PryHttpMiddleware` (auth, rate-limit, request-id, metrics) → CORS → routers.
  RFC 7807 Problem Details on 400/401/403/404/409/429/500/502/503.
- **Scraping Engine** — `UltimateScraper` 15-tier adaptive fallback; `BrowserPool`
  (Playwright/Camoufox/uc pooled); `proxy_manager`, `captcha/*`, `stealth_engine`,
  `cookie_warmer`, `quality`, CSS-selector ReDoS guard.
- **LLM Intelligence Layer** — 18 provider classes, fallback chain, cost tracker.
- **Payments / x402** — facilitator, SelfFacilitator (EIP-3009), scheme,
  solana_verifier, tron_verifier, batch.
- **Commerce / Billing** — billing_service (USD ledger), packs, subscription,
  enforcement tiers, signup, marketplace.

## 15-Tier Scraping Engine

`UltimateScraper.tier_order` (in `src/pry/engine/ultimate_scraper.py`) builds the
chain below, reordered per-domain by the adaptive registry
(`src/pry/engine/adaptive.py`). Each tier is wrapped in a per-domain circuit
breaker + retry config; a block signal short-circuits to the next tier and a
success locks the tier's priority for the domain's next request.

The 15 tiers: `direct` → `tls_fingerprint` → `cloudscraper` → `flaresolverr` →
`undetected` → `camoufox` → `playwright` → `googlebot` → `premium_proxy` → `tor`
→ `archive` → `google_cache` → `ai_visual` → `mobile_app` → `graphql`.

**Browser pooling (ADR-007).** Playwright, Camoufox, and undetected-chromedriver
browsers are pooled: launched once and reused (`new_context`/fresh page per
request; uc driver serialized via `threading.Lock`). `close_browsers()` is wired
to app lifespan shutdown for graceful close. Pooled browsers are never quit
inside the scrape loop.

**Shared httpx client.** `pry.core.client` (moved from `pry.api`) owns the shared
pooled `httpx.AsyncClient` (`get_client()`), reused across the no-proxy scrape
path and closed on shutdown.

**CSS-selector ReDoS guard.** Every user-supplied CSS selector is validated by
`_validate_css_selector()` (rejects >500 chars, >20 combinators, nested
quantifiers, char bombs) in `extraction/css.py`, `scraping/extraction.py`,
`scraping/structure.py`, and `pry_mcp/tools`.

## LLM Intelligence Layer

`src/pry/intelligence/llm/` is a provider-agnostic LLM abstraction: `base.py`
(`LLMProvider`, `cost_tracker`), `providers.py` (18 provider classes, registered
only when its key resolves plus always-on Ollama), and `registry.py`
(`LLMRegistry` with `fallback_chain`, per-provider retry, `PRY_LLM_PROVIDER_ORDER`).

## Payments / x402

`src/pry/payments/x402/` implements the x402 v1 spec: `scheme.py` (`X402_PRICING`,
7 networks, keccak256-ecdsa attestation), `facilitator.py` (`FacilitatorRouter`),
`self_facilitator.py` (EIP-3009 verify + settle), `handler.py` (verify/settle,
replay hardening), `solana_verifier.py`, `tron_verifier.py`, `batch.py`.
`x402_middleware/` is the enforcement layer (`X402Middleware` ASGI gate).

## Middleware / Enforcement

Middleware order in `src/pry/api/api.py` — **outermost first**:

1. **`X402Middleware`** — the payment gate (OUTERMOST). Any request not on a free
   path and matching a paid prefix is served a 402 challenge unless a valid
   `payment_id` / `PAYMENT-SIGNATURE` / batch id is present and verified. Sits
   outside auth so a keyless agent reaches the 402 challenge before 401.
2. **`PryHttpMiddleware`** — auth (Bearer API key or rmi JWT), per-key/per-IP
   rate limiting, request-id, timing, Prometheus metrics.
3. **`CORSMiddleware`** — allow-list locked to `pryscraper.com` + `rugmunch.io`
   (regex) and localhost dev origins. No `*`.
4. **FastAPI routers** — the application handlers.

RFC 7807 Problem Details are emitted by the error handlers for
400/401/403/404/409/429/500/502/503.

## MCP Server

`src/pry/api/api.py` mounts `create_mcp_app()` at `/mcp`:
- `/mcp` — Streamable HTTP transport.
- `/mcp/sse` — SSE transport.
- `/mcp/messages` — messages prefix; **auth-gated** (`request_authorized()`
  required for `tools/call` — fixed the unauthenticated SSE tool-execution hole).
- `/sse` — standalone SSE entry.
- stdio via `pry mcp serve` / `pry-mcp` / `pryscraper-mcp`.

`register_all()` binds all 76 `PRY_TOOLS`; `combined_tool_executor` runs
crypto/marketplace/data-domain tools locally and falls through to the REST proxy
for the rest.

## Observability

`docker-compose.yml` runs an **OpenTelemetry Collector** (`otel-collector`) +
**Jaeger** (`jaegertracing/all-in-one`). Setting `OTEL_EXPORTER_OTLP_ENDPOINT`
to `http://otel-collector:4318` routes traces to both the collector console and
Jaeger (UI at `127.0.0.1:16686`) for local/dev inspection. Config:
`otel/otel-collector-config.yaml`.

## Storage

Data lives under `PRY_DATA_DIR` (default `~/.pry`): `x402/` (payments,
settlements JSONL, nonce/replay), `llm_usage/`, `warmed_cookies/`, plus engine
state dirs. Durable app state in `PRY_DATABASE_URL` (SQLite dev / Postgres prod).

## External Dependencies

| Dependency | Purpose |
|------------|---------|
| FlareSolverr | Cloudflare/WAF challenge bypass (Docker sidecar) |
| Redis | Optional shared cache + rate limiting + MCP session store |
| Postgres | Durable database (default in prod) |
| Playwright / Camoufox / undetected-chromedriver | Pooled browser automation |
| Tor | Anonymous routing (optional) |
| x402 facilitator | External `coinbase`/`payai`/`cloudflare` verify+settle, OR self-facilitate |
| LLM providers | 18 provider families for AI extraction/scrape (free-first) |
| OTEL Collector + Jaeger | Distributed tracing (docker-compose) |

## Docs

- `STATUS.md` — where we are right now (update before each commit).
- `PLAN.md` — current sprint (update weekly).
- `DECISIONS.md` — architecture decision records (read before architectural changes).
