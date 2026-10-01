# Pry — API Reference

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry API Reference
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-08-30
audience:
  - engineers
  - agents (MCP clients)
  - integrators
note: Both the REST surface and the MCP tools are generated from the same FastAPI routers. The live OpenAPI spec is served at /openapi.json.
---

# API Reference

Pry exposes one API through two transports:

1. **REST** (`/v1/*`) — for humans, SDKs, and server-to-server automation.
2. **MCP** (`/mcp`, `/mcp/sse`, stdio) — 113 tools auto-discovered from the same
   routers, for AI agents. Each MCP tool maps back to a REST route.

**Route count.** `openapi.json` (built artifact) reports **293 paths** /
**~298 operations** across ~117 path-group prefixes, composed from 93 router
files under `src/pry/api/routers/**`. This table groups them by domain.

> **Base URL (cloud)**: `https://api.pryscraper.com`
> **Base URL (self-host)**: `http://localhost:8002` (or `:8005` from the Docker
> host port) · **MCP** at `/mcp/` · **OpenAPI** at `/openapi.json`.

---

## x402 Payment-Gated Flow

The core monetization model. When a client hits a **paid** endpoint without a
payment, the server responds **`402 Payment Required`** with an x402 manifest;
the client pays on-chain, then retries with the payment header.

```
Client                                        Server
  │  POST /v1/scrape                            │
  ├────────────────────────────────────────────►│  X402Middleware: paid op
  │  ◄──────────── 402 Payment Required ────────┤
  │  { x402Version, accepts:[{scheme, network,  │
  │    maxAmountRequired, asset, payToAddress}]} │
  │                                             │
  │  Pay 0.001 USDC on Base  ───────────────────▶│
  │    (signature in PAYMENT-SIGNATURE header   │
  │     OR X-Payment-Id for a pre-verified id)  │
  ├────────────────────────────────────────────►│
  │  ◄────────────── 200 + data ────────────────┤
  │            (+ PAYMENT-RESPONSE settlement)  │
```

**Headers (x402 v1)**:

| Header | Direction | Contents |
|--------|-----------|----------|
| `PAYMENT-REQUIRED` | 402 response | Base64 JSON x402 manifest (signed when attestation configured) |
| `PAYMENT-SIGNATURE` | request | Base64 JSON `{payment_id, tx_hash, network, asset, amount_usd}` |
| `PAYMENT-RESPONSE` | 2xx response | Base64 JSON settlement receipt |
| `X-Payment-Id` | request | A pre-verified payment id (covers replay-window reuse) |
| `X-Batch-Payment-Id` | request | A pre-verified batch payment id |

**Free vs paid** is decided by `x402_middleware/classification.py`. Fully free
(or fail-closed) surfaces include: `/health`, `/docs`, `/openapi.json`,
`/metrics`, the x402 flow itself (`/v1/x402/*`), `/v1/config`, `/v1/capabilities`,
`/v1/keys*`, `/v1/billing/*` (quote/purchase/balance — the monetary gate is the
x402 manifest), `/v1/job/*`, `/v1/session*`, `/v1/proxy/*` (control plane),
`.well-known/*`, `/llms.txt`. Everything else under a `PAID_ENDPOINTS` prefix is
gated.

---

## Core / Auth / Infra

| Group | Endpoints (representative) | Notes |
|-------|----------------------------|-------|
| Health | `/health`, `/healthz`, `/live`, `/ready`, `/version` | Always free |
| Auth | `/v1/auth/captcha`, `/v1/auth/credentials*`, `/v1/auth/sso`, `/v1/auth/session/health` | Free (control plane) |
| API keys | `/v1/keys`, `/v1/keys/{key_id}`, `/v1/keys/{key_id}/balance`, `/v1/keys/{key_id}/credit`, `/v1/keys/{key_id}/ledger` | Free (auth-gated) |
| Config | `/v1/config`, `/v1/config/profile/tor` | Free |
| Capabilities | `/v1/capabilities`, `/v1/ai/mcp-config`, `/v1/ai/gpt-manifest` | Free |
| Diagnostics | `/v1/diagnostics` | Free |
| Circuit breaker | `/v1/breaker/status`, `/v1/breaker/reset` | Free |
| Stats | `/v0/stats` | Free |
| System | `/v1/system` | Free |
| Admin | `{PRY_ADMIN_PATH}/admin/*` | Loopback-gated; free in x402 classification |

---

## Scraping (15-tier engine)

| Endpoint | Operation | Price | Description |
|----------|-----------|:-----:|-------------|
| `POST /v1/scrape` | `scrape` | $0.001 | Single URL → markdown |
| `GET /v1/scrape/methods` | `scrape_methods` | $0.002 | Per-domain method registry |
| `POST /v1/crawl` | `crawl` | $0.01 | Crawl up to 10 pages |
| `POST /v1/crawl/adaptive` | `crawl` | $0.01 | Adaptive crawl |
| `POST /v1/ultimate-scrape` | `scrape` | $0.001 | Force the full 15-tier chain |
| `POST /v1/map` | `crawl` | $0.01 | Site map (link graph) |
| `POST /v1/batch` | `bulk_crawl` | $0.10 | Batch crawl up to 1000 pages |

### Extraction / Parsing
| Endpoint | Operation | Price | Description |
|----------|-----------|:-----:|-------------|
| `POST /v1/extract` | `extract` | $0.005 | Structured extraction |
| `POST /v1/extract/css` | `extract` | $0.005 | CSS-selector extraction |
| `POST /v1/extract/llm` | `llm_call` | $0.01 | LLM extraction |
| `POST /v1/extract-table` | free * | $0 | Table extraction |
| `POST /v1/extract-with-review` | free * | $0 | Extract + human-in-the-loop review |
| `POST /v1/parse` | `pdf_extract` | $0.01 | Document parsing |
| `POST /v1/ocr/extract` | `ocr_extract` | $0.005 | Image OCR |
| `POST /v1/pdf/extract` | `pdf_extract` | $0.01 | PDF table extraction |
| `POST /v1/vision` | — | $0 | Vision model analysis |
| `POST /v1/vision/models` | — | $0 | List vision models |

### Automation / Browser
| Endpoint | Operation | Price | Description |
|----------|-----------|:-----:|-------------|
| `POST /v1/automate` | `browser_automation` | $0.05 | Browser automation (signup, form fill) |
| `POST /v1/capture` | `browser_automation` | $0.05 | Capture (network + lazy) |
| `POST /v1/capture/network` | `browser_automation` | $0.05 | Network capturing |
| `POST /v1/capture/lazy` | `browser_automation` | $0.05 | Lazy-load capture |
| `POST /v1/screenshot` | free * | $0 | Full-page screenshot |
| `POST /v1/camoufox/fetch` | free * | $0 | Camoufox render |

### Advanced / Specialty
| Endpoint | Operation | Price | Description |
|----------|-----------|:-----:|-------------|
| `POST /v1/graphql` | `graphql_query` | $0.003 | GraphQL discovery/query |
| `POST /v1/tls/impersonate`, `/v1/tls/rotate` | free * | $0 | TLS fingerprint */
| `POST /v1/shadow-dom` | free * | $0 | Shadow DOM extraction |
| `POST /v1/ws/scrape`, `/v1/sse/scrape` | free * | $0 | Streaming scrape |

> `*` = classified free by current explicit decision but is a **monetization
> candidate** (expensive scrape/data ops). See `classification.py` note block
> for the migration rule before moving any of these to paid.

---

## Monitoring

| Endpoint | Operation | Price | Description |
|----------|-----------|:-----:|-------------|
| `POST /v1/monitor` | `monitor` | $0.02 | Create a scheduled monitor |
| `POST /v1/monitor/run` | `monitor` | $0.02 | Run a monitor |
| `POST /v1/monitor/check` | `monitor` | $0.02 | One-shot check |
| `GET /v1/monitor/{monitor_id}` | — | $0 | Monitor detail |

---

## Data-Domain Intelligence (paid per call)

| Domain | Endpoint prefix | Operation | Price |
|--------|-----------------|-----------|:-----:|
| Legal | `/v1/legal/` | `legal_dockets` | $0.005 |
| Real estate | `/v1/realestate/` | `realestate_search` | $0.005 |
| Jobs | `/v1/jobs/` | `jobs_list` | $0.002 |
| Travel | `/v1/travel/` | `flights_grid` | $0.01 |
| Search/attention | `/v1/attention/` | `serp` | $0.003 |
| Local | `/v1/local/` | `places_search` | $0.003 |
| Government | `/v1/gov/` | `procurement` | $0.005 |
| IP | `/v1/ip/` | `patents` | $0.005 |
| Climate | `/v1/climate/` | `weather` | $0.002 |
| Research | `/v1/research/` | `academic` | $0.002 |
| Events | `/v1/events/` | `events_search` | $0.003 |
| Freight | `/v1/freight/` | `freight_rates` | $0.005 |
| Energy | `/v1/energy/` | `energy_lmp` | $0.002 |
| Food | `/v1/food/` | `food_grocery` | $0.002 |
| Supply | `/v1/supply/` | `supply_imports` | $0.004 |
| App store | `/v1/appstore/` | `app_store_search` | $0.002 |
| News | `/v1/news/` | `news_search` | $0.002 |
| Compliance | `/v1/compliance/enforcement`, `/v1/compliance/watch/` | `compliance_search` / `company_watch` | $0.003 / $0.005 |
| Deals | `/v1/deals/` | `deals_search` | $0.002 |
| Bidding | `/v1/bidding/` | `bidding_contracts` | $0.005 |
| Crypto | `/v1/crypto/` | `token_launches`, `cex_listings`, `token_security` | $0.002–$0.005 |

---

## Sports Betting (flat $0.01/scan)

| Endpoint | Operation |
|----------|-----------|
| `/v1/sports/odds` | `sports_odds` |
| `/v1/sports/stats` | `sports_stats` |
| `/v1/sports/scores` | `sports_scores` |
| `/v1/sports/arbitrage` | `sports_arbitrage` |
| `/v1/sports/plus-ev` | `sports_plus_ev` |
| `/v1/sports/props` | `sports_props` |
| `/v1/sports/injuries` | `sports_injuries` |
| `/v1/sports/live` | `sports_live` |
| `/v1/sports/historical` | `sports_historical` |
| `/v1/sports/betting-percentages` | `sports_betting_percentages` |
| `/v1/sports/sharp-consensus` | `sports_sharp_consensus` |
| `/v1/sports/alerts` | `sports_alerts` |
| `/v1/sports/books` (+ `/books/coverage`) | `sports_books` (112-book registry) |

---

## Templates & Pipelines

| Group | Endpoints | Operation | Price |
|-------|-----------|-----------|:-----:|
| Templates | `/v1/templates`, `/v1/templates/{template_id}` (list/get) | free | $0 |
| Templates | `/v1/templates/execute` | `template_execute` | $0.002 |
| Templates | `/v1/templates/batch` | `template_batch_execute` | $0.01 |
| Pipelines | `/v1/pipe`, `/v1/pipeline/*`, `/v1/pipelines*` | free (control) | $0 |

---

## Proxy Management (control plane — free)

`/v1/proxy/clicks`, `/v1/proxy/configure`, `/v1/proxy/pool`,
`/v1/proxy/providers`, `/v1/proxy/recommend`, `/v1/proxy/referrals*`,
`/v1/proxy/signup`, `/v1/proxy/status`, `/v1/proxy/test`. Proxy execution /
Tor profile config is explicitly guarded in the middleware + router layer (not
x402-gated, but auth-gated and loopback-only when no API key is set).

---

## Billing / Payments / Commerce

| Group | Endpoints | Notes |
|-------|-----------|-------|
| x402 | `/v1/x402/pricing`, `/v1/x402/catalog` | Free — quote the manifest |
| x402 | `/v1/x402/payment`, `/v1/x402/require-payment`, `/v1/x402/pay` | Free — issue/verify/settle |
| x402 | `/v1/x402/verify`, `/v1/x402/batch-verify`, `/v1/x402/batch-payment` | Free — part of the flow |
| Billing packs | `/v1/billing/packs`, `/v1/billing/purchase`, `/v1/billing/purchase/{invoice}/confirm` | Free control plane (arms server-side gate) |
| Subscription | `/v1/billing/subscription/invoice*`, `/v1/billing/signup`, `/v1/billing/balance` | Free control plane |
| Costing | `/v1/costing/costs`, `/v1/costing/dashboard`, `/v1/costing/usage`, `/v1/costing/record` | Free |
| Payments (crypto) | `/v1/payments/crypto/charge`, `/v1/payments/crypto/providers`, `/v1/payments/crypto/status/{charge}` | Free |
| Reconciliation | `/v1/reconcile`, `/v1/reconcile/schemas` | Free |
| Referrals | `/v1/referrals/catalog`, `/v1/referrals/click`, `/v1/referrals/convert`, `/v1/referrals/stats` | Free |
| Analytics | `/v1/analytics/payments` | Free (public) |

---

## Integrations (webhooks, alerts, GDPR, export)

`/v1/webhooks/*` (dead-letter, test) · `/v1/alert/channels`, `/v1/alert/send` ·
`/v1/destinations*`, `/v1/destination/send` · `/v1/export` ·
`/v1/crm/platforms`, `/v1/crm/sync` · `/v1/commerce/platforms`,
`/v1/commerce/search`, `/v1/commerce/sync`, `/v1/commerce/{marketplace}/{product}`
· `/v1/gdpr/*` (consent, deletion, retention, audit). All classified free.

---

## Discovery / Well-Known (public for AI agents)

| Endpoint | Purpose |
|----------|---------|
| `/.well-known/x402.json` | Payment manifest |
| `/.well-known/agent.json` | AI agent card |
| `/.well-known/x402-bazaar.json` | x402 Bazaar marketplace listing |
| `/llms.txt` | llms.txt standard for agent discovery |
| `/openapi.json`, `/docs`, `/redoc` | OpenAPI / interactive docs |

---

## MCP Tools → REST Mapping

MCP tools are auto-generated and enriched by `registry_metadata.py`. The
`fallback_server.py` `tool_map` wires each tool to a REST route. Examples:

| MCP tool | REST route |
|----------|-----------|
| `pry_scrape` | `POST /v1/scrape` |
| `pry_crawl` | `POST /v1/crawl` |
| `pry_extract` | `POST /v1/extract/css` |
| `pry_template` | `POST /v1/templates/execute` |
| `pry_search_templates` | `GET /v1/templates` |
| `pry_monitor` | `POST /v1/monitor` |
| `pry_compliance` | `POST /v1/compliance/check` |
| `pry_enrich` | `POST /v1/enrich` |
| `pry_parse_document` | `POST /v1/parse` |
| `pry_screenshot` | `POST /v1/screenshot` |
| `pry_x402_pricing` | `GET /v1/x402/pricing` |
| `pry_balance` | `POST /v1/billing/balance` |
| `pry_buy_pack` | `POST /v1/billing/purchase` |
| `pry_referrals` | `GET /v1/referrals/catalog` |
| `pry_odds` | `GET /v1/sports/odds` |
| `pry_legal_dockets` | `GET /v1/legal/dockets/search` |
| `pry_serp` | `GET /v1/attention/serp` |
| `pry_token_launches` | `GET /v1/crypto/token-launches` |

The full 113-tool list with per-category grouping is in
[docs/ops/TOOLS-CATALOG.md](TOOLS-CATALOG.md).

---

## Rate Limiting & Auth

- **Auth**: `PRY_API_KEY` set ⇒ every request must present
  `Authorization: Bearer <key>` (or a valid rmi JWT). Unset ⇒ only loopback
  clients allowed (every remote request rejected 401).
- **Rate limit**: per-key bearer token bucket (`PRY_RATE_LIMIT_RPM`, default 120)
  and per-IP shaper; shared Redis counters when `PRY_REDIS_URL` is reachable.
- **x402 gate RPM**: `X402_RATE_LIMIT_PER_MIN` (optional) caps paid-call traffic.
