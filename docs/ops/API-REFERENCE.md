# Pry — API Reference

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)

<!-- GENERATED FILE — do not edit. Regenerate: python3 scripts/gen_api_reference.py -->

Source: `openapi.json` (PryScraper API v3.0.0, OpenAPI 3.1.0).

- Paths: **373** · Operations: **380** · Tags: **85**
- `402` responses documented in the spec: **0 of 380**
- Auth column is inferred from router guards (`require_sensitive_config_auth`, hosting/admin gates), not from the spec — the spec declares no per-operation `security`.
- Error shapes (RFC 7807, FastAPI 422, legacy `success:false`, x402 402): see [`docs/ERRORS.md`](../ERRORS.md).

## 402 coverage

The audit found **0 of 380** operations declaring `402 Payment Required`, although the x402 middleware gates the paid routes below. Clients must treat an undocumented 402 as a normal payment challenge, not a failure. The next five routes to annotate:

| # | Method | Path | Summary |
|--:|--------|------|---------|
| 1 | POST | `/v1/scrape` | Scrape a single URL |
| 2 | POST | `/v1/crawl` | Crawl multiple pages from a URL |
| 3 | POST | `/v1/extract/css` | Extract structured data with CSS selectors (no LLM) |
| 4 | POST | `/v1/extract/llm` | Extract with LLM + chunking strategies |
| 5 | POST | `/v1/ultimate-scrape` | Scrape with 10-tier anti-bot fallback system |

## Tags

- [`Account`](#account) — 5 operations
- [`Admin`](#admin) — 29 operations
- [`Advanced`](#advanced) — 16 operations
- [`Agency`](#agency) — 7 operations
- [`AI`](#ai) — 2 operations
- [`Alerts`](#alerts) — 2 operations
- [`Analysis`](#analysis) — 6 operations
- [`Analytics`](#analytics) — 5 operations
- [`API Keys`](#api-keys) — 6 operations
- [`App Store Data`](#app-store-data) — 4 operations
- [`App UI`](#app-ui) — 4 operations
- [`Attention`](#attention) — 3 operations
- [`Auth`](#auth) — 8 operations
- [`Automation`](#automation) — 2 operations
- [`Batch`](#batch) — 1 operations
- [`Bidding Data`](#bidding-data) — 4 operations
- [`billing`](#billing) — 11 operations
- [`Capabilities`](#capabilities) — 1 operations
- [`Circuit Breaker`](#circuit-breaker) — 2 operations
- [`Climate Data`](#climate-data) — 2 operations
- [`Commerce`](#commerce) — 2 operations
- [`Commerce Data`](#commerce-data) — 3 operations
- [`Compliance`](#compliance) — 2 operations
- [`Compliance Data`](#compliance-data) — 3 operations
- [`Config`](#config) — 3 operations
- [`Costing`](#costing) — 4 operations
- [`CRM`](#crm) — 2 operations
- [`Crypto Market`](#crypto-market) — 3 operations
- [`Crypto Payments`](#crypto-payments) — 3 operations
- [`Dashboard`](#dashboard) — 1 operations
- [`Deals Data`](#deals-data) — 4 operations
- [`Diagnostics`](#diagnostics) — 2 operations
- [`Discovery`](#discovery) — 5 operations
- [`Email`](#email) — 3 operations
- [`Energy Data`](#energy-data) — 2 operations
- [`Enrichment`](#enrichment) — 2 operations
- [`Events Data`](#events-data) — 4 operations
- [`Execute`](#execute) — 1 operations
- [`Export`](#export) — 1 operations
- [`Extraction`](#extraction) — 9 operations
- [`Food Data`](#food-data) — 2 operations
- [`Freight Data`](#freight-data) — 2 operations
- [`Freshness`](#freshness) — 3 operations
- [`GDPR`](#gdpr) — 9 operations
- [`Government Data`](#government-data) — 3 operations
- [`Health`](#health) — 6 operations
- [`Healthcare Data`](#healthcare-data) — 4 operations
- [`hosting`](#hosting) — 10 operations
- [`Integrations`](#integrations) — 3 operations
- [`Intelligence`](#intelligence) — 4 operations
- [`IP Data`](#ip-data) — 4 operations
- [`Jobs`](#jobs) — 6 operations
- [`Legal & Public Records`](#legal-&-public-records) — 5 operations
- [`LocalData`](#localdata) — 3 operations
- [`Marketplace`](#marketplace) — 7 operations
- [`Monitoring`](#monitoring) — 5 operations
- [`News Data`](#news-data) — 4 operations
- [`Parsing`](#parsing) — 3 operations
- [`Pipeline`](#pipeline) — 3 operations
- [`Pipelines`](#pipelines) — 7 operations
- [`Proxy`](#proxy) — 10 operations
- [`Quality`](#quality) — 2 operations
- [`Real Estate`](#real-estate) — 3 operations
- [`Reconciliation`](#reconciliation) — 2 operations
- [`Recorder`](#recorder) — 4 operations
- [`Referrals`](#referrals) — 4 operations
- [`Reports`](#reports) — 3 operations
- [`Research Data`](#research-data) — 2 operations
- [`Review`](#review) — 6 operations
- [`Scraping`](#scraping) — 13 operations
- [`SEO`](#seo) — 3 operations
- [`Sessions`](#sessions) — 5 operations
- [`Share`](#share) — 2 operations
- [`Signup`](#signup) — 1 operations
- [`Sports Data`](#sports-data) — 16 operations
- [`Stats`](#stats) — 1 operations
- [`Structure`](#structure) — 3 operations
- [`Supply Data`](#supply-data) — 2 operations
- [`Templates`](#templates) — 4 operations
- [`Training`](#training) — 4 operations
- [`Transform`](#transform) — 2 operations
- [`Travel`](#travel) — 3 operations
- [`Vision`](#vision) — 2 operations
- [`Webhooks`](#webhooks) — 2 operations
- [`x402`](#x402) — 10 operations

## Account

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/account/api-keys/stats` | Per-API-key usage stats | Bearer | — |
| GET | `/v1/account/balance` | x402 prepaid balance | Bearer | — |
| GET | `/v1/account/billing-history` | Billing history (payments made) | Bearer | — |
| GET | `/v1/account/subscription` | Subscription details | Bearer | — |
| GET | `/v1/account/usage` | Current month's API usage for the authenticated user | Bearer | — |

## Admin

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/pry-admin-dev/v1/admin` | Admin HTML dashboard | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/actors` | Actor marketplace status: totals, runs today, revenue | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/actors/preview` | Actor catalog preview with icons, pricing, and revenue | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/actors/{actor_name}` | Single actor detail: spec, pricing, runs, revenue, error rate | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/analytics/overview` | Combined analytics dashboard (admin) | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/api-usage` | API usage stats: calls today, by endpoint, latency, errors, top users | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/apify` | Apify actor profit monitoring | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/config` | Show admin configuration status | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/dashboard` | Complete admin dashboard with profits and health | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/earnings` | Earnings: total + daily + by-stream + by-chain | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/earnings/apify` | Apify actor earnings: per-actor revenue and run volume | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/earnings/cloud` | Cloud subscription earnings: MRR, ARR, tiers, churn, LTV | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/earnings/combined` | Combined earnings from all revenue streams | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/earnings/treasury` | On-chain treasury wallet balances | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/health` | System health check | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/issues` | Outstanding customer issues and unresolved payments | admin key + loopback | — |
| POST | `/pry-admin-dev/v1/admin/issues/{issue_id}/resolve` | Mark a support issue as resolved | admin key + loopback | — |
| DELETE | `/pry-admin-dev/v1/admin/keys/{key_id}` | Revoke an API key (fail-closed: authenticate() rejects it immediately) | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/metrics` | Prometheus metrics for Grafana | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/payments/failed` | Failed payment verifications | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/payments/recent` | Last 50 payments from payments.jsonl | admin key + loopback | — |
| POST | `/pry-admin-dev/v1/admin/ping` | Health check with request body | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/profits` | Profit breakdown from x402 payments minus costs | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/revenue` | Revenue summary: totals, by tier, by chain, MRR, growth | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/users` | List accounts with balances, usage, and subscription status | admin key + loopback | — |
| GET | `/pry-admin-dev/v1/admin/users/{user_id}` | User detail: profile, recent API calls, subscription + billing history | admin key + loopback | — |
| POST | `/pry-admin-dev/v1/admin/users/{user_id}/credit` | Grant balance to a user | admin key + loopback | — |
| POST | `/pry-admin-dev/v1/admin/users/{user_id}/suspend` | Disable a user account | admin key + loopback | — |
| POST | `/pry-admin-dev/v1/admin/users/{user_id}/unsuspend` | Re-enable a suspended user account | admin key + loopback | — |

## Advanced

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/behavior/simulate` | Generate human-like behavior patterns for testing | — | — |
| POST | `/v1/camoufox/fetch` | Fetch with Camoufox anti-detection Firefox | — | — |
| GET | `/v1/cookies/sessions` | List all warmed cookie sessions | — | — |
| POST | `/v1/cookies/warm` | Warm cookies for a domain by browsing legitimate pages | — | — |
| POST | `/v1/dedup/check` | Check if content is a near-duplicate using SimHash | — | — |
| POST | `/v1/graphql/discover` | Discover GraphQL endpoints for a site | — | yes |
| POST | `/v1/graphql/introspect` | Run GraphQL introspection on an endpoint | — | yes |
| POST | `/v1/graphql/query` | Execute a GraphQL query | — | yes |
| POST | `/v1/ocr/extract` | Extract text from an image using Tesseract | — | — |
| POST | `/v1/pdf/extract` | Extract tables and text from a PDF | — | yes |
| POST | `/v1/schema/extract` | Extract Schema.org structured data from a page | — | — |
| POST | `/v1/schema/extract-html` | Extract Schema.org structured data from raw HTML | — | — |
| POST | `/v1/sse/scrape` | Scrape data from a Server-Sent Events endpoint | — | — |
| POST | `/v1/tls/impersonate` | Fetch a URL with TLS fingerprint impersonation | — | — |
| POST | `/v1/tls/rotate` | Try multiple browser fingerprints until one succeeds | — | — |
| POST | `/v1/ws/scrape` | Scrape data from a WebSocket endpoint | — | — |

## Agency

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/agency/create` | Create a white-label agency profile | — | — |
| GET | `/v1/agency/{agency_id}` | Get agency profile | — | — |
| GET | `/v1/agency/{agency_id}/analytics` | Get agency usage analytics | — | — |
| PUT | `/v1/agency/{agency_id}/branding` | Update agency branding | — | — |
| GET | `/v1/agency/{agency_id}/clients` | List agency clients | — | — |
| POST | `/v1/agency/{agency_id}/clients` | Create a client sub-account | — | — |
| GET | `/v1/client/{client_id}/quota` | Check client quota usage | — | — |

## AI

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/ai/gpt-manifest` | Get GPT Action manifest for ChatGPT | — | — |
| GET | `/v1/ai/mcp-config` | Get MCP server config for Claude/Cursor | — | — |

## Alerts

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/alert/channels` | List supported alert channels | — | — |
| POST | `/v1/alert/send` | Send an alert to any channel | — | — |

## Analysis

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/categorize` | AI-categorize scraped content | — | — |
| POST | `/v1/compare` | Compare content of two URLs | — | — |
| POST | `/v1/diff` | Track page changes over time | — | — |
| POST | `/v1/suggest` | AI-suggest schema fields for a URL | — | — |
| POST | `/v1/summarize` | AI summarize scraped content | — | — |
| POST | `/v1/watch` | Watch a page for changes | — | — |

## Analytics

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/analytics/api-popularity` | API endpoint popularity | — | — |
| GET | `/v1/analytics/funnel` | Signup funnel stats | — | — |
| GET | `/v1/analytics/payments` | Payment analytics dashboard | — | — |
| POST | `/v1/analytics/track` | Track a pageview or event | — | — |
| GET | `/v1/analytics/visitors` | Visitor and pageview stats | — | — |

## API Keys

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/keys` | List API keys | Bearer | — |
| POST | `/v1/keys` | Issue a new API key (plaintext shown once) | Bearer | — |
| DELETE | `/v1/keys/{key_id}` | Revoke an API key | Bearer | — |
| GET | `/v1/keys/{key_id}/balance` | Prepaid balance for a key's owner | Bearer | — |
| POST | `/v1/keys/{key_id}/credit` | Credit a key's owner balance | Bearer | — |
| GET | `/v1/keys/{key_id}/ledger` | Ledger entries for a key's owner | Bearer | — |

## App Store Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/appstore/apple/{app_id}` | Apple App Store app details by numeric App Store id | — | yes |
| GET | `/v1/appstore/apple/{app_id}/reviews` | Most recent Apple App Store customer reviews | — | yes |
| GET | `/v1/appstore/play/{package}` | Google Play app details by Android package id | — | yes |
| GET | `/v1/appstore/search` | Search apps on the Apple App Store and Google Play | — | yes |

## App UI

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/app` | App: keys and key status | — | — |
| POST | `/app/keys` | App: create a key (shown once) | — | — |
| POST | `/app/keys/{key_id}/revoke` | App: revoke a key | — | — |
| GET | `/app/usage` | App: usage this month | — | — |

## Attention

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/attention/ads` | Search the Meta Ad Library for active ads | — | yes |
| GET | `/v1/attention/serp` | Scrape Google SERP: organic results, AI Overview, People Also Ask | — | yes |
| GET | `/v1/attention/trends` | Google Trends interest over time + related queries | — | yes |

## Auth

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/auth/captcha` | Solve a CAPTCHA using third-party service | — | — |
| GET | `/v1/auth/credentials` | List stored credentials | — | — |
| POST | `/v1/auth/credentials` | Store credentials in the vault | — | — |
| DELETE | `/v1/auth/credentials/{credential_id}` | Delete stored credentials | — | — |
| POST | `/v1/auth/reset-password` | Request a password reset | — | — |
| POST | `/v1/auth/reset-password/confirm` | Confirm a password reset | — | — |
| POST | `/v1/auth/session/health` | Check authenticated session health | — | — |
| POST | `/v1/auth/sso` | Generate SSO login script | — | — |

## Automation

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/automate` | Execute browser automation steps | — | yes |
| POST | `/v1/screenshot` | Take a screenshot of a URL | — | — |

## Batch

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/batch-file` | Batch scrape URLs from a file with templates | — | yes |

## Bidding Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/bidding/contracts` | Search government contract solicitations + awards | — | yes |
| GET | `/v1/bidding/contracts/{contract_id}` | Get one contract by source-prefixed id | — | yes |
| GET | `/v1/bidding/grants` | Search federal grant opportunities (Grants.gov) | — | yes |
| GET | `/v1/bidding/grants/{grant_id}` | Get one grant by Grants.gov opp id | — | yes |

## billing

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/billing/balance` | Read an account's prepaid balance | Bearer | — |
| POST | `/v1/billing/packs` | List bulk scrape-credit packs | Bearer | — |
| POST | `/v1/billing/purchase` | Initiate a crypto-pack purchase (x402 PaymentRequired manifest) | Bearer | — |
| POST | `/v1/billing/purchase/{invoice_id}/confirm` | Verify a pack payment and credit the balance | Bearer | — |
| POST | `/v1/billing/signup` | Crypto signup — issue an API key + starter credits (no email) | Bearer | — |
| POST | `/v1/billing/subscription/cancel` | Cancel a subscription (stops auto-renewal, keeps access until period end) | Bearer | — |
| POST | `/v1/billing/subscription/change-tier` | Change the subscription tier | Bearer | — |
| POST | `/v1/billing/subscription/invoice` | Create a hosted subscription invoice (x402 PaymentRequired manifest) | Bearer | — |
| POST | `/v1/billing/subscription/invoice/{invoice_id}/confirm` | Verify a subscription payment and activate the subscription | Bearer | — |
| POST | `/v1/billing/subscription/renew` | Create a renewal invoice for the next subscription period | Bearer | — |
| GET | `/v1/billing/subscription/status` | Get the current subscription status for an API key | Bearer | — |

## Capabilities

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/capabilities` | Detect deployment capabilities | — | — |

## Circuit Breaker

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/breaker/reset` | Reset circuit breaker for a domain | — | — |
| POST | `/v1/breaker/status` | Get circuit breaker status | — | — |

## Climate Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/climate/agri` | USDA NASS crop prices received | — | yes |
| GET | `/v1/climate/forecast` | NOAA NWS forecast, current conditions and alerts for a lat/lon point | — | yes |

## Commerce

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/commerce/platforms` | List supported commerce platforms | — | — |
| POST | `/v1/commerce/sync` | Sync products to WooCommerce or Shopify | — | — |

## Commerce Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/commerce/search` | Search products across eBay, Etsy, AliExpress, or a Shopify store | — | — |
| GET | `/v1/commerce/{marketplace}/{product_id}` | Get a single product by id on a marketplace | — | — |
| GET | `/v1/social/{platform}/{handle}` | Public follower metrics for a social profile | — | — |

## Compliance

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/compliance/check` | Get compliance check documentation | — | — |
| POST | `/v1/compliance/check` | Run full compliance check on a URL | — | — |

## Compliance Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/compliance/enforcement` | Search regulatory enforcement actions (FDA/FTC/CFPB/SEC) | — | yes |
| GET | `/v1/compliance/enforcement/{agency}/{action_id}` | Get one enforcement action by agency + prefixed id | — | yes |
| GET | `/v1/compliance/watch/{company}` | Company compliance screening (enforcement/complaint matches) | — | yes |

## Config

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/config` | Get current Pry configuration | Bearer | — |
| POST | `/v1/config` | Update Pry configuration at runtime | Bearer | — |
| POST | `/v1/config/profile/tor` | Enable Tor routing for all requests | Bearer | — |

## Costing

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/costing/costs` | Update per-operation cost table | — | — |
| GET | `/v1/costing/dashboard` | Get cost analytics dashboard | — | — |
| POST | `/v1/costing/record` | Record a usage event | — | — |
| GET | `/v1/costing/usage` | Get usage breakdown | — | — |

## CRM

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/crm/platforms` | List supported CRM platforms | — | — |
| POST | `/v1/crm/sync` | Sync scraped data to CRM | — | — |

## Crypto Market

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/crypto/cex-listings` | Get recent CEX listing and delisting signals | — | yes |
| GET | `/v1/crypto/token-launches` | Get new crypto token launches, pairs, or trending tokens | — | yes |
| GET | `/v1/crypto/token-security/{chain}/{address}` | Run a security scan on a token | — | yes |

## Crypto Payments

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/payments/crypto/charge` | Create a crypto payment charge | — | — |
| GET | `/v1/payments/crypto/providers` | List configured providers | — | — |
| GET | `/v1/payments/crypto/status/{charge_id}` | Check payment status | — | — |

## Dashboard

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/analytics/payments` | Payment analytics dashboard | — | — |

## Deals Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/deals/drops/check` | Resolve prices + report drop-alert trigger state | — | yes |
| GET | `/v1/deals/drops/set` | Create a product restock/price-drop alert | — | yes |
| GET | `/v1/deals/search` | Search deals across Slickdeals / RetailMeNot | — | yes |
| GET | `/v1/deals/store/{store}` | Deals/coupons for one retailer | — | yes |

## Diagnostics

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/diagnostics` | Fallback telemetry diagnostics | — | — |
| GET | `/v1/diagnostics/method-plan` | Learned method memory for one domain (why a fetch is ordered this way) | — | — |

## Discovery

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/.well-known/agent.json` | Agent Card | — | — |
| GET | `/.well-known/server.json` | Mcp Server Manifest | — | — |
| GET | `/.well-known/x402-bazaar.json` | X402 Bazaar | — | — |
| GET | `/.well-known/x402.json` | X402 Manifest | — | — |
| GET | `/llms.txt` | Llms Txt Endpoint | — | — |

## Email

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/email/gmail` | Fetch and extract data from Gmail inbox | — | — |
| POST | `/v1/email/outlook` | Fetch and extract data from Outlook inbox | — | — |
| POST | `/v1/email/scrape` | Extract data from an email (subject + body) | — | — |

## Energy Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/energy/fuel-prices` | Weekly retail fuel prices from EIA | — | yes |
| GET | `/v1/energy/lmp` | ISO day-ahead locational marginal prices | — | yes |

## Enrichment

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/enrich` | Enrich scraped data with company info, tech stack, social profiles | — | — |
| POST | `/v1/enrich/tech-stack` | Detect technologies used on a website | — | — |

## Events Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/events/search` | Search events via Ticketmaster Discovery | — | yes |
| GET | `/v1/events/{event_id}` | Get a single event's detail | — | yes |
| GET | `/v1/events/{event_id}/history` | Tracked resale price history for an event | — | yes |
| GET | `/v1/events/{event_id}/resale` | Resale listings for an event (StubHub / SeatGeek) | — | yes |

## Execute

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/run` | Execute a Pryfile | — | — |

## Export

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/export` | Export scraped content in multiple formats | — | — |

## Extraction

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/emails` | Find email addresses on a page | — | — |
| POST | `/v1/extract` | Extract structured fields from a URL | — | — |
| POST | `/v1/extract-table` | Extract HTML tables as structured data | — | — |
| POST | `/v1/extract/css` | Extract structured data with CSS selectors (no LLM) | — | yes |
| POST | `/v1/extract/llm` | Extract with LLM + chunking strategies | — | yes |
| POST | `/v1/links` | Analyze links on a page | — | — |
| POST | `/v1/schema` | Extract Schema.org/JSON-LD structured data | — | — |
| POST | `/v1/seo` | SEO analysis of a page | — | — |
| POST | `/v1/thumbnail` | Extract og:image/thumbnail from a URL | — | — |

## Food Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/food/grocery` | Grocery prices for a product query in a ZIP code | — | yes |
| GET | `/v1/food/restaurant/{name}` | Restaurant menu for a restaurant name | — | yes |

## Freight Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/freight/fmc/contracts` | Federal Maritime Commission agreements matching a query | — | yes |
| GET | `/v1/freight/rates` | Container spot rates (40ft) per trade lane — Freightos FBX + Drewry WCI fallback | — | yes |

## Freshness

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/freshness/check` | Check if content has changed since last scrape | — | — |
| GET | `/v1/freshness/dashboard` | Get content staleness dashboard | — | — |
| POST | `/v1/freshness/frequency` | Get adaptive scrape frequency recommendation | — | — |

## GDPR

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/gdpr/audit` | Get compliance audit log | Bearer | — |
| POST | `/v1/gdpr/consent` | Record user consent for data processing | Bearer | — |
| POST | `/v1/gdpr/consent/revoke` | Revoke user consent | Bearer | — |
| GET | `/v1/gdpr/consent/{user_id}` | Check user consent status | Bearer | — |
| POST | `/v1/gdpr/deletion/execute` | Execute data deletion request | Bearer | — |
| POST | `/v1/gdpr/deletion/request` | Request data deletion (right to erasure) | Bearer | — |
| POST | `/v1/gdpr/domain/purge` | Purge all stored data for a domain (dry-run by default) | Bearer | — |
| GET | `/v1/gdpr/retention` | Get data retention policy | Bearer | — |
| POST | `/v1/gdpr/retention/apply` | Apply retention policy to remove expired data | Bearer | — |

## Government Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/gov/procurement/search` | Search federal procurement opportunities (SAM.gov) | — | yes |
| GET | `/v1/gov/procurement/{notice_id}` | Get one SAM.gov opportunity by notice id | — | yes |
| GET | `/v1/gov/recalls/search` | Search CPSC + FDA product recalls | — | yes |

## Health

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/health` | Health summary — gated by CRITICAL deps only | — | — |
| GET | `/healthz` | Pure liveness — always 200 while serving | — | — |
| GET | `/live` | Kubernetes liveness probe | — | — |
| GET | `/ready` | Kubernetes readiness probe | — | — |
| GET | `/readyz` | Readiness probe | — | — |
| GET | `/version` | Service version | — | — |

## Healthcare Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/health/drug/{drug}` | Get a US drug price by name (NADAC + GoodRx) | — | — |
| GET | `/v1/health/insurance/quotes` | Car/home insurance quote feasibility + public rate tables | — | — |
| GET | `/v1/health/trials/search` | Search clinical trials by keyword (clinicaltrials.gov) | — | — |
| GET | `/v1/health/trials/{nct_id}` | Get one clinical trial by NCT id | — | — |

## hosting

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/hosting/instances` | List the caller's hosted instances | Bearer | — |
| GET | `/v1/hosting/instances/{instance_id}` | Hosted instance details | Bearer | — |
| POST | `/v1/hosting/instances/{instance_id}/cancel` | Cancel a hosted subscription | Bearer | — |
| POST | `/v1/hosting/instances/{instance_id}/renew` | Create a renewal invoice for a hosted instance | Bearer | — |
| GET | `/v1/hosting/plans` | List hosted-instance plans | Bearer | — |
| GET | `/v1/hosting/portal` | Customer portal — instances, usage and API keys | Bearer | — |
| POST | `/v1/hosting/portal/request` | Request a portal magic-link (emailed to the customer) | Bearer | — |
| POST | `/v1/hosting/signup` | Create a hosting signup invoice (x402 402 payment manifest) | Bearer | — |
| POST | `/v1/hosting/signup/{invoice_id}/confirm` | Verify a hosting payment and provision the instance | Bearer | — |
| POST | `/v1/hosting/signup/{invoice_id}/verify` | Verify the signup email for a hosting invoice | Bearer | — |

## Integrations

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/destination/send` | Send scraped data to a business destination | — | — |
| GET | `/v1/destinations` | List supported data destinations | — | — |
| POST | `/v1/scrape-and-send` | Scrape a URL and send to a destination | — | yes |

## Intelligence

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/intel/analyze` | Analyze competitor field for anomalies | — | — |
| POST | `/v1/intel/report` | Generate a competitive intelligence report | — | — |
| POST | `/v1/intel/snapshot` | Record a competitor data snapshot | — | — |
| GET | `/v1/intel/snapshots/{competitor_id}` | Get competitor snapshots | — | — |

## IP Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/ip/companies/search` | Search a state company registry (Secretary of State) | — | yes |
| GET | `/v1/ip/patents/search` | Search patents via Google Patents | — | yes |
| GET | `/v1/ip/patents/{patent_id}` | Get a single patent by publication number | — | yes |
| GET | `/v1/ip/trademarks/search` | Search US trademarks via USPTO | — | yes |

## Jobs

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/job/{job_id}` | Get async job status and result | — | — |
| GET | `/v1/jobs` | List jobs in a Pryfile | — | — |
| GET | `/v1/jobs/salary/{company}` | Salary bands for a company/role from Levels.fyi | — | yes |
| GET | `/v1/jobs/search` | Cross-board job search | — | yes |
| GET | `/v1/jobs/{board}/job/{job_id}` | Get one job's full detail from an ATS board | — | yes |
| GET | `/v1/jobs/{board}/{company}` | List job postings from an ATS board | — | yes |

## Legal & Public Records

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/legal/dockets/search` | Search U.S. court dockets (CourtListener) | — | yes |
| GET | `/v1/legal/dockets/{docket_id}` | Get one court docket by CourtListener id | — | yes |
| GET | `/v1/legal/sanctions/{name}` | Screen a name against the OFAC SDN sanctions list | — | yes |
| GET | `/v1/legal/sec/insider/{ticker}` | Get recent Form 4 insider-trade filings for a ticker | — | yes |
| GET | `/v1/legal/sec/search` | Search SEC EDGAR filings by ticker and form type | — | yes |

## LocalData

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/local/places/search` | Search Google Maps for local businesses | — | yes |
| GET | `/v1/local/places/{place_id}` | Get a Google Maps place (detail + popular times) | — | yes |
| GET | `/v1/local/reviews/{place_id}` | Get review history for a place (Google Maps / Yelp) | — | yes |

## Marketplace

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/actors` | List actors in the marketplace | — | — |
| POST | `/v1/actors/create` | Create a new actor | — | — |
| POST | `/v1/actors/{actor_id}/run` | Run an actor | — | — |
| GET | `/v1/marketplace/amazon/product/{asin}` | Get an Amazon product by ASIN | — | — |
| GET | `/v1/marketplace/amazon/search` | Search Amazon products | — | — |
| GET | `/v1/marketplace/tiktok/trending` | Get TikTok Shop trending products | — | — |
| GET | `/v1/marketplace/walmart/product/{product_id}` | Get a Walmart product by product ID | — | — |

## Monitoring

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/monitor` | Create a scheduled content monitor | — | yes |
| POST | `/v1/monitor/check` | Run all due monitors | — | yes |
| POST | `/v1/monitor/run` | Run a single monitor check | — | yes |
| DELETE | `/v1/monitor/{monitor_id}` | Delete a monitor | — | yes |
| GET | `/v1/monitors` | List all monitors | — | yes |

## News Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/news/article` | Extract a full article (text + summary + metadata) | — | yes |
| GET | `/v1/news/headlines` | Recent headlines matching a query (GDELT + RSS) | — | yes |
| GET | `/v1/news/sentiment` | Aggregate sentiment for a query (GDELT tone + keyword fallback) | — | yes |
| GET | `/v1/news/timeline` | Per-day entity timeline with tone + top sources | — | yes |

## Parsing

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/markdown` | Generate markdown with content filtering strategies | — | — |
| POST | `/v1/parse` | Parse a document (PDF, DOCX, image, CSV, JSON) | — | — |
| POST | `/v1/shadow-dom` | Extract content from Shadow DOM | — | — |

## Pipeline

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/pipeline/hook` | Register a hook function | — | — |
| GET | `/v1/pipeline/hooks` | List all registered hooks | — | — |
| POST | `/v1/pipeline/run` | Run pipeline hooks for testing (deprecated; sunset 2027-04-18) | — | — |

## Pipelines

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/pipelines` | List saved pipelines | Bearer | — |
| POST | `/v1/pipelines/run` | Execute a pipeline | Bearer | — |
| POST | `/v1/pipelines/save` | Save a pipeline definition | Bearer | — |
| GET | `/v1/pipelines/steps` | List all available pipeline step types | Bearer | — |
| POST | `/v1/pipelines/validate` | Validate a pipeline definition | Bearer | — |
| DELETE | `/v1/pipelines/{pipeline_id}` | Delete a saved pipeline | Bearer | — |
| GET | `/v1/pipelines/{pipeline_id}` | Get a saved pipeline | Bearer | — |

## Proxy

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/proxy/clicks` | Get recent proxy referral clicks | — | — |
| POST | `/v1/proxy/configure` | Configure proxy credentials | Bearer | — |
| GET | `/v1/proxy/pool` | List the Webshare residential proxy pool | — | — |
| GET | `/v1/proxy/providers` | List all available proxy providers | — | — |
| POST | `/v1/proxy/recommend` | Get proxy recommendation after a block | — | — |
| GET | `/v1/proxy/referrals` | List proxy provider affiliate referrals | — | — |
| GET | `/v1/proxy/referrals/{tag}` | Get a single proxy provider referral | — | — |
| POST | `/v1/proxy/signup` | Open affiliate signup link for a provider | — | — |
| GET | `/v1/proxy/status` | Get current proxy status | — | — |
| GET | `/v1/proxy/test` | Test the active proxy | — | — |

## Quality

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/quality/check` | Run data quality check on extraction results | — | — |
| GET | `/v1/quality/stats` | Get quality statistics for all checked URLs | — | — |

## Real Estate

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/realestate/listing/{zillow_id}` | Look up a single real-estate listing by Zillow id | — | yes |
| GET | `/v1/realestate/property/{county}/{parcel_id}` | Look up a county property record by parcel id | — | yes |
| GET | `/v1/realestate/search` | Search real-estate listings by location | — | yes |

## Reconciliation

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/reconcile` | Reconcile records from multiple sources into unified entities | — | — |
| GET | `/v1/reconcile/schemas` | List supported reconciliation schemas | — | — |

## Recorder

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/record/clear` | Clear recorded actions | — | — |
| POST | `/v1/record/export` | Export recording as script | — | — |
| POST | `/v1/record/start` | Start recording browser actions | — | — |
| POST | `/v1/record/step` | Record a browser action step | — | — |

## Referrals

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/referrals/catalog` | Get all available referral/affiliate programs | — | — |
| POST | `/v1/referrals/click` | Record a referral link click | — | — |
| POST | `/v1/referrals/convert` | Record a referral conversion | — | — |
| GET | `/v1/referrals/stats` | Get referral click and conversion stats | — | — |

## Reports

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/report/{report_id}` | Get a generated report | — | — |
| GET | `/v1/reports` | List generated reports | — | — |
| POST | `/v1/reports/generate` | Generate a white-label report from scraped data | — | — |

## Research Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/research/domain/{domain}` | RDAP WHOIS lookup for a domain | — | yes |
| GET | `/v1/research/papers` | Search scholarly papers (OpenAlex primary, Crossref fallback) | — | yes |

## Review

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/extract-with-review` | Extract with automatic human review routing | — | — |
| POST | `/v1/review/submit` | Submit extracted data for human review | — | — |
| GET | `/v1/review/{review_id}` | Get review details | — | — |
| POST | `/v1/review/{review_id}/approve` | Approve a review item | — | — |
| POST | `/v1/review/{review_id}/reject` | Reject a review item | — | — |
| GET | `/v1/reviews` | List reviews in the queue | — | — |

## Scraping

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/batch` | Scrape multiple URLs in parallel | — | yes |
| POST | `/v1/capture/lazy` | Detect and handle lazy-loaded content | — | yes |
| POST | `/v1/capture/network` | Extract API calls and network patterns from a page | — | yes |
| POST | `/v1/crawl` | Crawl multiple pages from a URL | — | yes |
| POST | `/v1/crawl/adaptive` | Crawl with adaptive stopping based on content relevance | — | yes |
| DELETE | `/v1/crawl/{job_id}` | Cancel an async crawl job | — | yes |
| GET | `/v1/crawl/{job_id}` | Get async crawl job status | — | yes |
| GET | `/v1/crawl/{job_id}/errors` | List per-URL crawl failures | — | yes |
| POST | `/v1/detect-block` | Detect if a site is blocking the scraper | — | — |
| POST | `/v1/map` | Discover URLs on a site (legacy success/data.links deprecated) | — | yes |
| POST | `/v1/scrape` | Scrape a single URL | — | yes |
| POST | `/v1/search` | Search the web | — | yes |
| POST | `/v1/ultimate-scrape` | Scrape with 10-tier anti-bot fallback system | — | yes |

## SEO

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/seo/analyze` | Analyze SEO elements from a URL | — | — |
| POST | `/v1/seo/keywords` | Analyze keyword presence in URL content | — | — |
| POST | `/v1/seo/track` | Track SEO changes since last scan | — | — |

## Sessions

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/session/create` | Create a persistent browser session | — | — |
| POST | `/v1/session/destroy` | Destroy a browser session with optional save | — | — |
| POST | `/v1/session/restore` | Restore a saved session | — | — |
| POST | `/v1/session/save` | Save current session state to disk | — | — |
| GET | `/v1/sessions` | List all persistent sessions | — | — |

## Share

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/share/{share_id}` | View shared content | — | — |
| POST | `/v1/share` | Share scraped content via link | — | — |

## Signup

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/signup` | Automatically register an account | — | — |

## Sports Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/scrape/methods` | Sportsbook scraping-method registry | — | yes |
| GET | `/v1/sports/alerts` | Money-printer alerts (line moves, steam, CLV) | — | yes |
| GET | `/v1/sports/arbitrage` | Arbitrage opportunities across bookmakers | — | yes |
| GET | `/v1/sports/betting-percentages` | Public betting percentages (bets & money share) | — | yes |
| GET | `/v1/sports/books` | Aggregated odds across the 112-book sportsbook registry | — | yes |
| GET | `/v1/sports/books/coverage` | Sportsbook coverage-registry statistics (112 books, 5 categories) | — | yes |
| GET | `/v1/sports/historical` | Historical betting odds for past events | — | yes |
| GET | `/v1/sports/injuries` | Injury report for a sport or team | — | yes |
| GET | `/v1/sports/live` | Live in-play odds | — | yes |
| GET | `/v1/sports/odds` | Live betting odds across bookmakers | — | yes |
| GET | `/v1/sports/odds/{event_id}` | Multi-sportsbook odds comparison for one event | — | yes |
| GET | `/v1/sports/plus-ev` | Positive-EV betting opportunities vs a sharp book | — | yes |
| GET | `/v1/sports/props` | Player prop betting lines | — | yes |
| GET | `/v1/sports/scores` | Scores for a day (ESPN) | — | yes |
| GET | `/v1/sports/sharp-consensus` | Sharp consensus lines (CLV-aware) | — | yes |
| GET | `/v1/sports/stats/{player}` | Player stats (ESPN) | — | yes |

## Stats

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v0/stats` | Get cache, rate limiter, and session stats (deprecated; sunset 2027-04-18) | — | — |

## Structure

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/structure/check` | Check if CSS selectors still match on a page | — | — |
| POST | `/v1/structure/check-template` | Verify a scraper template still works | — | — |
| POST | `/v1/structure/monitor` | Monitor page structure changes over time | — | — |

## Supply Data

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/supply/firmographics/{company}` | B2B firmographics for a company (website, tech stack, hiring, funding) | — | yes |
| GET | `/v1/supply/imports/{company}` | ImportYeti/Panjiva-style import records for a company | — | yes |

## Templates

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/templates` | List all pre-built scraper templates | — | — |
| POST | `/v1/templates/batch` | Execute multiple templates/URLs in parallel | — | yes |
| POST | `/v1/templates/execute` | Execute a scraper template against a URL | — | yes |
| GET | `/v1/templates/{template_id}` | Get a scraper template | — | — |

## Training

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/training/classify-license` | Classify content license for AI training | — | — |
| POST | `/v1/training/clean` | Strip PII and copyright from content | — | — |
| GET | `/v1/training/compliance/{dataset_id}` | Generate compliance report for a dataset | — | — |
| POST | `/v1/training/export` | Export a clean AI training dataset | — | — |

## Transform

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/pipe` | Scrape and transform via data pipeline | — | — |
| POST | `/v1/transform` | Transform data to multiple formats | — | — |

## Travel

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/travel/flights/grid` | Cheapest flight per day over a date range (Google Flights) | — | yes |
| GET | `/v1/travel/flights/search` | Search one-way flights for a single date (Google Flights) | — | yes |
| GET | `/v1/travel/hotels/rates` | Per-night hotel rates for a stay window (Google Hotels / Booking.com) | — | yes |

## Vision

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| POST | `/v1/vision` | Analyze an image with a free vision model | — | — |
| GET | `/v1/vision/models` | List free vision-capable models on OpenRouter | — | — |

## Webhooks

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/v1/webhooks/dead-letter` | Get failed webhook deliveries | — | — |
| POST | `/v1/webhooks/test` | Test webhook delivery | — | — |

## x402

| Method | Path | Summary | Auth | 402 possible |
|--------|------|---------|------|--------------|
| GET | `/supported` | Supported x402 payment kinds | — | — |
| POST | `/v1/x402/batch-payment` | Create a batch x402 payment | — | — |
| POST | `/v1/x402/batch-verify` | Verify a batch x402 payment | — | — |
| GET | `/v1/x402/catalog` | Full x402 catalog: operations, engines and every Apify actor preset | — | — |
| GET | `/v1/x402/health` | x402 readiness/health probe | — | — |
| POST | `/v1/x402/pay` | Process x402 payment and get access token | — | — |
| POST | `/v1/x402/payment` | Create a x402 payment request | — | — |
| GET | `/v1/x402/pricing` | Get x402 pricing for all paid operations | — | — |
| POST | `/v1/x402/require-payment` | Generate a 402 Payment Required response | — | — |
| POST | `/v1/x402/verify` | Verify a x402 payment was settled | — | — |
