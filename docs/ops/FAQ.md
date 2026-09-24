# Pry — Frequently Asked Questions

## General

**What is Pry?**
A self-hosted web scraping and browser-automation API. Point it at any URL
and get clean markdown, structured JSON, screenshots, or parsed documents —
with a 12-tier fallback chain that escalates through anti-bot bypasses only
as far as the target requires.

**How is this different from Firecrawl/ScrapingBee/…?**
Three ways: (1) self-hosted — your infrastructure, your data, no per-page
markup; (2) adaptive tier selection remembers what works per domain instead
of re-paying the bypass cost every request; (3) native x402 micropayments,
so you can also *run* Pry as a paid API without building billing.

**What are the 12 tiers?**
Direct HTTP → TLS fingerprint impersonation → cloudscraper → FlareSolverr →
undetected-chromedriver → Camoufox → Playwright → Googlebot emulation →
Tor → premium proxy → archive.org → Google Cache. The chain order adapts
per domain from live success history, and circuit breakers skip tiers whose
backing services are down.

**Which sites can it handle?**
Sites behind Cloudflare, DataDome, Akamai, Imperva and similar WAFs are
handled by the browser/stealth tiers. Sites requiring logins are not (yet) —
session persistence exists for cookie reuse but credential auth is out of
scope for the core API.

## Payments (x402)

**How does pay-per-call work?**
Scraping endpoints return `402 Payment Required` with a signed payment
challenge. Pay it with any x402-compatible client (USDC on Base via
EIP-3009 `transferWithAuthorization`) and retry with the payment proof.
No account, no key, no minimum. See the [README](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/README.md#paid-api-x402).

**What happens if I underpay?**
Verification recovers the signer cryptographically and compares the
authorized amount against the server-side price. Underpayments are rejected
with an explicit reason — nothing is settled, nothing is consumed.

**Can a payment be replayed or redirected?**
No. Every authorization names the operator's wallet (recipient pinning),
carries a per-token nonce that is burned on first use (replay protection),
and expires on a second-precision window (`validAfter`/`validBefore`).
Tampering with any field breaks the signature recovery and fails verification.

**Do free endpoints need payment?**
No. Health/metrics/docs, job & session management, GDPR data-subject
endpoints, webhook management, and the x402 flow itself are free by design.
The full classification is explicit in the source
(`x402_middleware.DEFAULT_FREE_PATHS`) and audited at boot.

**Is the pricing gate fail-open?**
The opposite. Every route must be classified at startup — an unclassified
route fails the boot audit in strict mode, and a paid route missing its
price refuses requests (HTTP 500 + alert) rather than serving content free.

## Operations

**What are the minimum resources?**
The API alone runs comfortably in 1 vCPU / 1 GB. Browser tiers want 2 GB+
and Chromium deps (the Docker image ships them). PostgreSQL and Redis are
recommended in production; SQLite works for single-instance dev.

**How do I scale it horizontally?**
Run replicas behind a load balancer with Postgres as the database and Redis
configured — the rate limiter automatically switches to Redis-backed
counters shared across replicas when `PRY_REDIS_URL` is reachable.
See [DEPLOYMENT.md](DEPLOYMENT.md).

**How do I monitor it?**
`/metrics` (Prometheus), OpenTelemetry traces via
`OTEL_EXPORTER_OTLP_ENDPOINT`, and drop-in SLO alert rules in
[`prometheus/alerts.yml`](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/prometheus/alerts.yml). A Grafana-friendly admin
dashboard ships at `<admin-path>/v1/admin/dashboard`.

**Where do my results go?**
Nowhere unless you send them. Pry has no telemetry home; DataBus forwarding
to rmi-backend is opt-in and self-configured.

## Integration

**Can AI agents use it?**
Yes — Pry is MCP-native: it mounts a spec-compliant MCP server at `/mcp`
(SSE + streamable HTTP) so Claude Desktop, Cursor, or any MCP client can
scrape directly. An `mcp-config` endpoint emits ready-made client config.

**Does it work with Apify?**
Yes. The repo ships a complete Apify Actor definition (`.actor/`) — build
it once and run Pry's scraper as an Actor with Apify proxies and dataset
output. CI validates the packaging on every change and publishes when
`APIFY_TOKEN` is configured.

**Is there a Python SDK?**
Yes — async (`PryCrawl`) and sync (`PryCrawlSync`) clients ship in the
package. See the [README](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/README.md#python-sdk).

## Troubleshooting

**402 on an endpoint I expected to be free?**
Check `/v1/x402/pricing` for the operation and its price. Route
classification is explicit; if you self-patched routes, add them to
`DEFAULT_FREE_PATHS` or `PAID_ENDPOINTS`.

**All scrapes return `status: error`?**
Check `/health` dependencies (FlareSolverr/Redis/Ollama optional), then the
admin dashboard's per-tier success rates. If every tier fails the target is
likely offline or blocking all exits — try `tor` or `premium_proxy` tiers
explicitly.

**Webhooks aren't delivering?**
Pry refuses to send unsigned webhooks. Set `PRY_WEBHOOK_SECRET` (or gopass
`pry/webhook_secret`) and check the dead-letter queue at
`/v1/webhooks/dead-letter`.
