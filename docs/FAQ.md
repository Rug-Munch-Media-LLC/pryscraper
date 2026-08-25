# Pry — FAQ

The full product guide lives on [pryscraper.com](https://pryscraper.com).
These are the questions developers actually ask before running Pry.

- [Capabilities](#capabilities)
- [Anti-bot & scraping power](#anti-bot--scraping-power)
- [x402 payments](#x402-payments)
- [MCP & AI agents](#mcp--ai-agents)
- [Apify Actors](#apify-actors)
- [Self-hosting & operations](#self-hosting--operations)
- [Legal & compliance](#legal--compliance)
- [Troubleshooting](#troubleshooting)

## Capabilities

**What exactly is Pry?**
A self-hosted web scraping and browser-automation API with native
[x402](https://www.x402.org) micropayments. One engine, three surfaces: a
REST API, an MCP server for AI agents, and 94 store-ready Apify Actors.

**What can it fetch?**
Any public URL → clean markdown, structured JSON (CSS/XPath schemas),
PDF/DOCX/image text, full-page screenshots, and site-wide crawls. On top of
that: 110+ pre-built templates for common sites and 27 long-tail data
domains (crypto, legal, jobs, travel, energy, gov procurement, …).

**How is this different from just calling Firecrawl/ScraperAPI?**
Three ways. (1) Self-hosted — your infrastructure, your data, no per-page
resale markup. (2) Payment-native — x402 pay-per-call in USDC; no accounts,
no API keys, no subscriptions. (3) MCP-native — AI agents get the same
capabilities as typed tools, not scraped HTML docs.

**Does it need a database?**
No. SQLite zero-config by default; set `PRY_DATABASE_URL` to Postgres for
production metering/billing durability.

## Anti-bot & scraping power

**It really bypasses Cloudflare?**
Pry escalates through a 12-tier adaptive chain — plain HTTP, TLS
fingerprinting, cloudscraper, FlareSolverr, undetected-chromedriver,
Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, cached
copies — and *remembers* which tier worked per domain, so repeat visits go
straight to the right tier. Block-signal detection classifies captcha/WAF/
rate-limit pages and jumps families instead of retrying blindly.

**What if a tier gets me blocked anyway?**
Circuit breakers quarantine flaky tiers per domain, and the adaptive
ordering demotes them from live success/failure history. You see exactly
which tier served each response in the telemetry.

**How fast is it?**
Cheap targets resolve on tier 1 (plain HTTP) in milliseconds. The k6 smoke
gate in CI fails the build on p95 regressions, so the serving path stays
fast by construction.

## x402 payments

**How does pay-per-call work?**
Every paid endpoint speaks [x402](https://www.x402.org): call it without
payment and you get a `402` carrying a signed payment challenge (amount,
recipient, asset, network). Pay it with any x402 client — EIP-3009
`transferWithAuthorization` in USDC — attach the proof header, retry, done.
No account creation ever.

**Do I need an API key?**
No. A verified on-chain payment **is** the credential. API keys exist for
teams that prefer quotas and invoicing; x402 callers skip them entirely.

**Which chains and assets?**
Multi-chain by design — Base plus Ethereum/L2s, Solana, TRON; USDC/USDT
stables first, native assets supported. The 402 challenge lists every
accepted network/asset so any compliant wallet can pay.

**Where do I see prices?**
`GET /v1/x402/pricing` for the operation price table,
`GET /v1/x402/catalog` for the full machine-readable catalog — every priced
operation, every paid endpoint, and all 94 Apify actors bound to their
equivalent MCP tool. Both are keyless.

**Can I underpay or replay a payment?**
No. Server-side pricing is authoritative (client-claimed amounts are
rejected before facilitator verification), recipient is pinned to the
configured wallet, nonces are single-use, and validity windows are enforced
to the second.

## MCP & AI agents

**Is there an MCP server?**
Yes — 71 tools covering scrape/crawl/extract/monitor/screenshot/templates
plus every data domain. Streamable HTTP + SSE at `/mcp`, or stdio via
`uvx pryscraper-mcp`. See [`llms.txt`](../llms.txt) for the full
machine-readable tool and actor index.

**Why MCP instead of wrapping the REST API?**
Typed tools with schemas mean the agent doesn't parse prose to figure out
parameters. Pry's MCP surface is generated from the same contracts the API
enforces, so tool docs can't drift from behavior.

## Apify Actors

**94 actors? What are they?**
Store-ready packages of the same engine, one per job family — universal
scraper, site crawler, change monitors, CVE watchers, lead harvesters,
price watchers, and 20+ niche domain collectors. Each ships its own
INPUT_SCHEMA, pricing events, and Dockerfile; the catalog endpoint (and
[`llms.txt`](../llms.txt)) indexes them all.

**Do actors settle in USDC too?**
On Apify they bill through the platform (pay-per-event). The same
capability behind each actor is available x402-native through the API/MCP.

**How do I build one locally?**
```bash
python -m actor_factory.cli stage <actor-name> /tmp/stage
cd /tmp/stage/<actor-name> && apify run --purge
```

## Self-hosting & operations

**Minimum setup?**
```bash
docker compose up -d        # API + FlareSolverr + Redis
curl localhost:8005/healthz
```
Single container works too (`docker run ghcr.io/rugmunchmedia/pry`) —
FlareSolverr just upgrades your bypass ceiling.

**How do I monitor it?**
Prometheus metrics at `/metrics` (route-template cardinality control
included), OpenTelemetry spans per scrape attempt, ready-made SLO burn-rate
alerts in [`prometheus/alerts.yml`](../prometheus/alerts.yml), and a k6
performance gate in CI. The on-call flow lives in
[RUNBOOK.md](RUNBOOK.md).

**What happens when a dependency (Redis, FlareSolverr) dies?**
Health endpoints degrade honestly (`/ready` vs `/healthz` split), circuit
breakers shed load toward working tiers, and nothing crashes the serving
loop — metering and webhooks fail closed, never silently.

## Legal & compliance

**Is scraping legal?**
Pry is a tool; compliance is yours. It ships a compliance scorer
(`pry_compliance`) that grades robots.txt/ToS/GDPR-CCPA exposure per target
so you can make informed calls. Respect applicable law and site terms.

**Do you respect robots.txt?**
Pry can honor robots directives per deployment configuration, and reports
compliance risk per URL. It does not make legal decisions for you.

## Troubleshooting

**Scrape returns a challenge page?**
That tier was insufficient for this target — check `scrape.tier` in the
response metadata; if the max tier still fails, the target likely needs
residential proxies (configure `proxy_config`).

**402 says "misconfigured"?**
A route lost its pricing entry — this is fail-closed by design. Check the
startup audit output; the fix is adding the operation to the pricing table,
never serving free.

**Webhooks aren't arriving?**
Without `PRY_WEBHOOK_SECRET` configured, deliveries are *refused*, not sent
unsigned. Set the secret (restart not required for new deliveries).

**Where are usage/billing records?**
The `Usage` table (Postgres in production) — one row per request with key
identity, route template, status, duration. The admin metrics endpoint
aggregates them live.
