# x402 Pricing

Pry monetizes **per call** with the [x402](https://docs.x402.org/) protocol
(HTTP 402 Payment Required). No accounts, no subscriptions for the
pay-as-you-go path — pay only for what you use. Prices are set
**server-side** (`X402_PRICING` in `src/pry/payments/x402/scheme.py`); the
server never trusts a client-supplied amount.

## Core operations

| Operation | Price |
|-----------|:-----:|
| `scrape` | $0.001 |
| `crawl` (up to 10 pages) | $0.01 |
| `bulk_crawl` | $0.10 |
| `extract` (CSS selectors) | $0.005 |
| `schema_extract` | $0.002 |
| `template_execute` | $0.002 |
| `template_batch_execute` | $0.01 |
| `pdf_extract` | $0.01 |
| `ocr_extract` | $0.005 |
| `llm_call` | $0.01 |
| `browser_automation` | $0.05 |
| `monitor` | $0.02 |
| `graphql_query` | $0.003 |

## Domain tiers

After the domain/tier merges the live surface is **64 priced operations**.
Representative tiers:

- Sports betting — flat **$0.01/scan** across all 99 tools
- Legal / real estate / patents / trademarks — $0.005
- Jobs / travel / search / local / news — $0.002–$0.01
- Crypto (launches, CEX listings, security) — $0.002–$0.005
- Free: template listing, screenshots, KOL leaderboards, control plane

## Networks & assets

USDC in atomic units on supported networks (Base `eip155:8453` and others —
see [networks](networks)). The 402 challenge lists every accepted
scheme/network/asset combination.

## Subscriptions & packs

Prefer a flat rate? See the hosted paths: crypto subscriptions
(Pro/Team/Enterprise) and bulk scrape-credit packs —
[overview](overview).
