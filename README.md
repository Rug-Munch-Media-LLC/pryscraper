[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)

<div align="center">

# Pry — Open any website

**Self-hosted web scraping & browser automation API with native x402 micropayments**

[![CI](https://git.rugmunch.io/RugMunchMedia/pryscraper/badges/workflows/ci.yml/badge.svg)](https://git.rugmunch.io/RugMunchMedia/pryscraper/actions)
[![Coverage](https://img.shields.io/endpoint?url=https://codecov.io/gh/cryptorugmuncher/pryscraper/coverage.json 2>/dev/null || true)](https://github.com/cryptorugmuncher/pryscraper)
![Tests](https://img.shields.io/badge/tests-3500%2B_passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![x402](https://img.shields.io/badge/payments-x402%20%2F%20USDC-blueviolet)

**12-tier anti-bot bypass** · Cloudflare, DataDome, Akamai · **Pay-per-call API** via USDC · **Runs as an Apify Actor** · MCP-native for AI agents

[`Quickstart`](#quickstart) · [`Paid API (x402)`](#paid-api-x402) · [`Self-host`](#docker) · [`Apify Actor`](#run-it-as-an-apify-actor) · [`FAQ`](FAQ.md) · [`Deployment`](DEPLOYMENT.md)

</div>

---

## Why Pry

Every scraper breaks the moment a site turns on Cloudflare. Pry routes each
request through an adaptive 12-tier fallback chain — plain HTTP, TLS
fingerprinting, cloudscraper, FlareSolverr, undetected-chromedriver,
Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, and cached
copies — escalating only as far as the target actually requires, then
remembering what worked per domain.

- **Adaptive tier ordering** — the chain reorders itself from live success/failure history per domain
- **Block-signal detection** — classifies captcha / WAF / rate-limit pages and jumps to the right bypass family
- **Circuit breakers** — flaky upstream services stop wasting your latency budget
- **Honest telemetry** — OpenTelemetry spans per scrape attempt, Prometheus metrics with route-level cardinality control, SLO burn-rate alerts included

## Quickstart

```bash
pip install -e .          # or: pip install pryscraper-mcp
pry serve                 # API on :8002

pry open https://example.com                        # clean markdown
pry open https://store.com/product --json --schema product.json
pry crawl https://docs.com --max-pages 20 -o data.json
```

Docker (full stack with FlareSolverr):

```bash
docker compose up -d      # Pry :8005 → :8002, FlareSolverr :8192 → :8191
```

## Paid API (x402)

Pry's scraping endpoints speak [x402](https://www.x402.org): HTTP-native
micropayments in USDC on Base. No accounts, no API keys, no subscriptions —
every 402 response carries a payment request; attach proof of payment and
the same request succeeds.

```bash
# 1. Discover the price
curl http://localhost:8005/v1/x402/pricing | jq '.operations.scrape'

# 2. First call returns 402 + payment challenge
curl -i http://localhost:8005/v1/scrape -X POST \
     -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'

# 3. Pay the challenge with any x402 client (EIP-3009 transferWithAuthorization),
#    then retry with the payment header:
curl http://localhost:8005/v1/scrape -X POST \
     -H 'Content-Type: application/json' \
     -H 'X-PAYMENT: <signed-payment-payload>' \
     -d '{"url":"https://example.com"}'
```

**Payment guarantees** (all enforced server-side, fully test-covered):
- EIP-3009 signer recovery — tampered amounts/recipients fail signature verification
- Recipient pinning — funds only ever authorize to the configured wallet
- Replay protection — per-token nonce store; a used authorization is dead
- Expiry windows — `validAfter`/`validBefore` enforced to the second
- Fail-closed gate — every route is classified at boot; a misconfigured price refuses requests rather than leaking them free

Free forever: health/metrics/docs, job & session management, GDPR endpoints,
webhook management, and the x402 payment flow itself.

## Run it as an Apify Actor

Pry ships as a ready-to-build Apify Actor (`.actor/`): point it at URLs,
get markdown/metadata in your Apify dataset, billed through Apify's platform.

```bash
apify run --purge          # local run
apify push                 # deploy to Apify Console (CI does this automatically)
```

Input: `urls`, `crawl`, `max_pages`, `timeout`, `output_format`,
`proxy_config`. See [.actor/actor.json](.actor/actor.json) for the full schema.

## CLI Reference

| Command | Description |
|---------|-------------|
| `pry open <url>` | Scrape URL to clean markdown |
| `pry watch <url>` | Monitor page for changes |
| `pry crawl <url>` | Crawl multiple pages |
| `pry batch <file>` | Batch scrape URLs from file |
| `pry parse <url>` | Parse PDF/DOCX/image |
| `pry ss <url>` | Take screenshot |
| `pry run [pry.yml]` | Execute job file |
| `pry serve` | Start API server |

## Python SDK

```python
from pry_sdk import PryCrawl          # async
from pry_sdk import PryCrawlSync      # sync

mc = PryCrawl("http://localhost:8005")
result = await mc.scrape("https://example.com")
print(result["data"]["markdown"])
```

| Method | Description |
|--------|-------------|
| `scrape(url, **opts)` | Scrape to markdown |
| `scrape_json(url, schema, **opts)` | Scrape with JSON extraction |
| `crawl(url, max_pages, **opts)` | Crawl site |
| `map(url, limit)` | Discover URLs |
| `parse(url)` | Parse document |
| `automate(steps, **opts)` | Browser automation |
| `screenshot(url)` | Screenshot page |
| `health()` | Service health |


<!-- mcp-name: io.rugmunch/pry -->
| `scrape(url, **opts)` | Scrape to markdown |
| `scrape_json(url, schema, **opts)` | Scrape with JSON extraction |
| `crawl(url, max_pages, **opts)` | Crawl site |
| `map(url, limit)` | Discover URLs |
| `parse(url)` | Parse document |
| `automate(steps, **opts)` | Browser automation |
| `screenshot(url)` | Screenshot page |
| `health()` | Service health |

## MCP (AI Agent Integration)

<!-- mcp-name: io.rugmunch/pry -->

## Observability & Operations

- **Metrics**: Prometheus at `/metrics` and `<admin>/v1/admin/metrics` — request rates/latency by route template, scrape outcomes by method, cache behaviour, x402 gate counters.
- **Tracing**: OpenTelemetry spans across the scrape pipeline (`scrape.request` → per-tier `scrape.tier`). Enable with `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Alerts**: ready-made SLO burn-rate rules in [`prometheus/alerts.yml`](prometheus/alerts.yml) — availability budget, scrape success rate, p95 latency, payment-gate misconfiguration.
- **Performance gate**: k6 smoke (10 VUs) runs in CI on every change to the serving path; thresholds catch gross regressions before they merge.

## Security Posture

- Fail-closed auth: key configured ⇒ Bearer required from every source; keyless ⇒ loopback only
- Fail-closed payments: unclassified or mispriced routes refuse traffic instead of serving free
- Fail-closed webhooks: deliveries without a configured signing secret are refused, never sent unsigned
- SSRF guard on every fetch target; admin surface is loopback-only behind a random prefix
- Pinned dependency lock (`requirements.lock`) installed verbatim in Docker and CI; drift check fails the build
- Gitleaks, semgrep, bandit, pip-audit, hadolint gates on every commit

## Deployment

Production checklist, environment matrix, scaling notes, and backup guidance
live in [DEPLOYMENT.md](DEPLOYMENT.md). Common questions are answered in
[FAQ.md](FAQ.md).

## Development

```bash
pip install -e ".[dev]"
pre-commit install
pytest -m "not integration"        # 3,500+ tests
k6 run perf/smoke.js               # performance smoke (needs local server)
```

Quality gates: ruff (lint+format), mypy strict on core modules, mutmut
mutation baseline on parsing/dedup/quality logic, coverage floor 74%,
commitlint, AI-test-oracle attribution checks.

## License

MIT — see [LICENSE](LICENSE).
