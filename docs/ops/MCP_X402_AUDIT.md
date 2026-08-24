[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry MCP + x402 Audit & 20-Win Improvement Plan
status: canonical
owner: Engineering
last_updated: 2026-07-01
---

# Pry MCP + x402 Audit & 20-Win Improvement Plan

> Researched current standards (modelcontextprotocol.io, coinbase/x402 GitHub) and identified 20 critical improvements.

## Implementation Status

| # | Win | Status | Notes |
|---|-----|--------|-------|
| 1 | Fix MCP `tools/call` response format | **Done** | `mcp_production.py` returns `{"content": [...], "isError": bool}` |
| 2 | Add `prompts/list` and `prompts/get` | **Done** | 7 real prompts with argument injection |
| 3 | Real x402 facilitator integration | **Done** | `x402.py` calls Coinbase + PayAI `/verify` and `/settle` |
| 4 | Multi-chain x402 support | **Done** | 13 chains, asset-aware `accepts` array |
| 5 | MCP `outputSchema` for every tool | **Done** | All 12 tools declare output schemas |
| 6 | x402 `PaymentRequirements` with multiple `accepts` | **Done** | Per-chain USDC/USDT/DAI/etc. options |
| 7 | Smithery + Glama + PulseMCP directory listings | **Done** | `smithery.yaml`, `glama.json`, `pulsemcp.json` |
| 8 | Cloudflare Worker deployment | **Done** | `workers/mcp-worker.js` + `wrangler.toml` |
| 9 | Resource subscriptions | **Done** | `resources/subscribe`, `notifications/resources/updated/list_changed` |
| 10 | `completion/complete` endpoint | **Done** | Template ID, max_pages, format autocompletion |
| 11 | HTTP+SSE transport for MCP | **Done** | `/mcp/sse` + `/mcp/messages/{session_id}`; integration-tested with uvicorn; middleware is pure ASGI to avoid buffering |
| 13 | Multi-facilitator smart router | **Done** | `FacilitatorRouter` with health tracking + EIP-7702 fallback |
| 14 | x402 batch payments | **Done** | `POST /v1/x402/batch-payment` + `/v1/x402/batch-verify` |
| 15 | `prompts/get` with embedded resources | **Partial** | Prompts reference resources by URI in text; full embedded resource spec pending |
| 16 | x402 EIP-7702 self-verify mode | **Done** | EVM receipt polling fallback |
| 17 | MCP `logging` capability | **Done** | `logging/setLevel`, `notifications/message` forwarding |
| 18 | x402 settlement receipt | **Done** | `PAYMENT-RESPONSE` header with tx/block/facilitator |
| 19 | MCP server health check endpoint | **Done** | `GET /mcp/health` |
| 20 | `annotations` on all resources | **Done** | audience + priority on 4 resources |

**Remaining:** MCP Apps (#12) — UI widget spec is still stabilizing; will revisit once modelcontextprotocol.io finalizes the schema.

---

## Current State vs. Standards

### MCP (Model Context Protocol)

| Standard Requires | Pry Has | Gap |
|-------------------|---------|-----|
| JSON-RPC 2.0 protocol over stdio | ✅ Fallback implemented | Official SDK class used opportunistically |
| `initialize` with protocolVersion | ✅ Returns `2024-11-05` | OK |
| `tools/list` with proper JSON Schema | ✅ 12 tools | OK |
| `tools/call` with content array | ✅ Returns proper content array | OK |
| `resources/list` and `resources/read` | ✅ Implemented with live data | OK |
| `prompts/list` and `prompts/get` | ✅ 7 prompts | OK |
| `notifications/resources/updated` | ✅ Via notification observers | OK |
| `completion/complete` | ✅ Implemented | OK |
| `logging/setLevel` | ✅ Implemented + log forwarding | OK |
| `roots/list` | ❌ Missing | Intentionally omitted — Pry is server-side |
| **FastMCP** decorator pattern | ⚠️ Fallback dict-of-tools | Official SDK path stubbed; not required for compliance |
| `outputSchema` for tools | ✅ All tools | OK |
| `annotations` on resources | ✅ All resources | OK |
| Resource subscriptions | ✅ `resources/subscribe` + `unsubscribe` | OK |
| HTTP+SSE transport | ✅ `/mcp/sse` + `/mcp/messages/{sid}` | OK |

**Our MCP score: 9/10 — spec-compliant on all required methods except roots/list (out of scope).**

### x402 (HTTP 402 Payment Required)

| Standard Requires | Pry Has | Gap |
|------------------|---------|-----|
| HTTP 402 status code with PaymentRequired body | ✅ Returns 402 | OK |
| `x402Version: 1` in response | ✅ | OK |
| `accepts` array (multiple payment options) | ✅ Multiple chains/assets | OK |
| `PaymentRequirements` schema | ✅ Full schema | OK |
| `PaymentPayload` signing | ✅ `PAYMENT-SIGNATURE` header decoded | OK |
| `PAYMENT-REQUIRED` header (Base64 JSON) | ✅ | OK |
| `PAYMENT-RESPONSE` header on success | ✅ Settlement receipt | OK |
| Facilitator integration (`/verify`, `/settle`) | ✅ Coinbase + PayAI | OK |
| Multiple chains | ✅ 13 chains | OK |
| USDC amounts in atomic units (6 decimals) | ✅ | OK |
| `network` per chain | ✅ | OK |
| `scheme: "exact"` | ✅ | OK |
| `extra` field | ✅ Includes operation, batch_id | OK |
| **Coinbase facilitator** | ✅ Via `x402.org/facilitator` | OK |
| **EIP-7702 self-verify** | ✅ Fallback RPC polling | OK |
| Settlement receipt | ✅ tx hash, block, facilitator | OK |
| Multi-facilitator smart router | ✅ Health tracking + fallback | OK |
| Batch payments | ✅ `/v1/x402/batch-payment` | OK |

**Our x402 score: 9/10 — production-ready payment flow with fallback paths.**

## Top 20 Wins (Ranked by Revenue Impact)

### Tier 1: Immediate Revenue ($100K+ MRR potential)

| # | Win | Why | Effort |
|---|-----|-----|--------|
| 1 | **Fix MCP `tools/call` response format** — Return `{"content": [{"type": "text", "text": "..."}]}` not raw dict | AI agents can't parse our responses. One-line fix. | 1h |
| 2 | **Add `prompts/list` and `prompts/get`** — Pre-built prompt templates like "research a company", "compare products", "extract all emails" | Prompts are how AI users discover server capabilities. RMI doesn't have these. | 4h |
| 3 | **Real x402 facilitator integration** — Call real Coinbase/PayAI facilitator to verify + settle payments | Without this, payments don't actually work. The current "verify" just records a payment. | 1d |
| 4 | **Multi-chain x402 support** — Match RMI's 13 chains (Base, Solana, ETH, Polygon, Arbitrum, TRON, BTC, etc.) | Each chain is a market. Currently we only have Base. | 1d |
| 5 | **MCP `outputSchema` for every tool** — Declare what each tool returns | AI agents can validate responses. Standard requirement. | 4h |
| 6 | **x402 `PaymentRequirements` with multiple `accepts`** — Per-call chain selection | Customers want to pay in their preferred token. One chain = lost revenue. | 4h |

### Tier 2: Adoption (the network effect)

| # | Win | Why | Effort |
|---|-----|-----|--------|
| 7 | **Smithery + Glama + PulseMCP directory listings** — List Pry in MCP directories | Discovery = users. These are THE MCP directories. | 2h |
| 8 | **Cloudflare Worker deployment** — Run the MCP server on Cloudflare Workers for easy hosting | Users can't self-host easily. Hosted = revenue. | 1d |
| 9 | **Resource subscriptions** — Push updates to clients when monitors fire | Real-time value. AI agents can react to changes. | 1d |
| 10 | **`completion/complete` endpoint** — Autocomplete parameter values (e.g., suggest URLs, template IDs) | Better UX in AI clients. Standard requires this. | 4h |
| 11 | **HTTP+SSE transport for MCP** — Not just stdio | Claude web, n8n, Zapier integrations need HTTP transport | 1d |
| 12 | **MCP Apps (UI elements)** — Interactive widgets in chat that show scraped data | The newest MCP spec feature. Huge UX win. | 2d |

### Tier 3: Premium features (the moat)

| # | Win | Why | Effort |
|---|-----|-----|--------|
| 13 | **Multi-facilitator smart router** — Auto-pick best facilitator (lowest fee, fastest confirmation) per chain | Without this, x402 is fragile. | 2d |
| 14 | **x402 batch payments** — Pay for 100 scrapes with one transaction | Bulk users want this. Standard supports it via `PaymentPayload` with multiple `PaymentRequirements`. | 1d |
| 15 | **`prompts/get` with embedded resources** — "Compare products" prompt that auto-injects the catalog resource | Showcases full MCP capability. Differentiator. | 1d |
| 16 | **x402 EIP-7702 self-verify mode** — No facilitator needed, direct on-chain verification | Zero dependencies. Leading implementations support this. | 1d |
| 17 | **MCP `logging` capability** — Server sends structured log messages to client | Critical for debugging. Standard. | 4h |

### Tier 4: Polish

| # | Win | Why | Effort |
|---|-----|-----|--------|
| 18 | **x402 settlement receipt** — Return tx hash, block number, network, timestamp in `PAYMENT-RESPONSE` header | Customers need receipts. Standard requires this. | 2h |
| 19 | **MCP server health check endpoint** — `/health` reports MCP server status, tools count, version | Production ops need this. | 2h |
| 20 | **`annotations` on all resources** — `audience: ["user", "assistant"]`, `priority: 0.8` | Better AI client UX. Standard feature. | 1h |

## How to Ship This (Practical Order)

| Week | Deliverables | Expected MRR |
|------|-------------|--------------|
| **Week 1** | Fix #1, #5, #18, #19, #20 (MCP response format, output schemas, x402 receipt, health, annotations) | $0 → enables usage tracking |
| **Week 2** | #3, #4, #6, #13, #16 (Real facilitator, multi-chain, multi-accept, smart router, EIP-7702) | $0 → first revenue |
| **Week 3** | #2, #10, #11, #15, #17 (Prompts, completion, HTTP+SSE, embedded resources, logging) | $5K → adoption |
| **Week 4** | #7, #8, #9, #12, #14 (Directory listings, Cloudflare Worker, subscriptions, MCP Apps, batch payments) | $20K+ → scale |

## What I'd Build RIGHT NOW (Top 5 highest leverage)

1. **Fix MCP `tools/call` format** — AI agents can't even use our current server
2. **Add `prompts/list` and `prompts/get`** — Biggest differentiator, zero competitors have it
3. **Real x402 facilitator integration** — Without this, no real revenue
4. **Multi-chain `accepts` array** — Capture all payment networks
5. **Cloudflare Worker deployment** — Self-hosting is friction

## Where the Money Is

- **Per-call pricing**: $0.001 (scrape) to $0.05 (browser automation) — x402 standard pricing
- **Volume**: Apify does $100M+ ARR. Pry can capture 1-5% as a lighter alternative = $1-5M ARR
- **Real revenue starts**: Week 2 (after real facilitator)
- **Profitability**: 90%+ (no compute, no labor, pure infrastructure)
- **Competitive moat**: 110 templates, 9-tier fallback, referral network = hard to replicate
