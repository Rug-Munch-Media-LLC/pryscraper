<div align="center">

<img src="website/static/img/pry-logo.png" alt="Pry logo" width="360">

# Pry — open any website

**Self-hosted scraping and browser automation with x402 pay-per-call.**

[api.pryscraper.com](https://api.pryscraper.com) · Python 3.11+ · MIT + BSL-1.1

</div>

## What it is

Pry turns a URL into Markdown, structured JSON, or a screenshot. It escalates through 15 anti-bot tiers only as far as a site needs, then remembers which tier worked for that domain.

## Why it is different

- **One engine, three doors.** REST, CLI, and 99 MCP tools resolve to the same scraper. `pry_mcp/tool_routes.py` maps every MCP tool to an HTTP route.
- **Escalation is learned per domain.** The engine records which tier succeeded and prefers it next time (`src/pry/engine/resilience.py`, `src/pry/engine/tier_score.py`).
- **Payment is per request.** An unpaid call returns HTTP 402 with the price and payee; the client pays on-chain and retries. No account, no subscription (`src/pry/payments/x402/`).

## 30-second quickstart

```bash
pip install pryscraper-mcp
PRY_X402_ENABLED=false PRY_API_KEY=devkey pry serve    # http://127.0.0.1:8005
```

```bash
curl -s http://127.0.0.1:8005/v1/scrape \
  -H 'Authorization: Bearer devkey' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
```

```json
{
  "success": true,
  "data": {
    "markdown": "# Example Domain\n\nThis domain is for use in illustrative examples...",
    "metadata": {
      "url": "https://example.com",
      "method": "direct",
      "title": "Example Domain",
      "description": "",
      "offset": 0,
      "total": 1256
    }
  }
}
```

`method` names the tier that served the page. `total` is the full Markdown length; `offset` and `limit` page through large bodies (`ScrapeRequest`, `src/pry/api/routers/scraping/scraping_models.py`).

## What you can do

| Job | Endpoint | Request |
|---|---|---|
| Scrape one page | `POST /v1/scrape` | `{"url":"https://example.com"}` |
| Crawl a site | `POST /v1/crawl` | `{"url":"https://example.com","maxPages":10}` |
| Map URLs | `POST /v1/map` | `{"url":"https://example.com","limit":50}` |
| Extract fields | `POST /v1/extract` | `{"url":"https://shop.example/p/1","fields":{"price":"Price in USD"}}` |
| Run a template | `POST /v1/templates/execute` | `{"template_id":"amazon_product","url":"https://amazon.com/dp/..."}` |

Crawl returns `{"success":true,"data":{"id":"sync","url":"...","pages":[...]}}`. Map returns `data.links`. Extract returns the requested keys as JSON. Templates read from `src/pry/commerce/templates/` (110 files).

All 99 tools are callable over MCP at `/mcp/` (Streamable HTTP) or `/mcp/sse` (SSE). Discovery is keyless; execution needs an API key or an x402 payment.

## Pricing

| Operation | USD per call | Operation key |
|---|---:|---|
| Scrape one URL | $0.001 | `scrape` |
| Crawl up to 10 pages | $0.010 | `crawl` |
| Structured extraction | $0.005 | `extract` |
| Execute a template | $0.002 | `template_execute` |
| Create a monitor | $0.020 | `monitor` |

Source: `X402_PRICING` in `src/pry/payments/x402/scheme/pricing/catalog.py`. The live table is `GET /v1/x402/pricing`.

Seven networks settle: Base, Ethereum, Arbitrum, Optimism, Polygon, Solana, TRON (`CAIP2_NETWORK_IDS`, `src/pry/payments/x402/scheme/networks.py`). A 402 advertises `accepts[]` with `network`, `asset`, `maxAmountRequired` (atomic units), and `payToAddress`.

```bash
curl -s https://api.pryscraper.com/v1/scrape -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'
# 402 Payment Required -> pay the quoted amount -> retry with PAYMENT-SIGNATURE
```

## Self-host

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
cp .env.selfhost.example .env.selfhost
./scripts/selfhost-init.sh
PRY_SELFHOST_PORT=8005 docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost up -d
```

API `http://localhost:8005`, MCP `http://localhost:8005/mcp/`, health `http://localhost:8005/health`. The container listens on 8002; `PRY_SELFHOST_PORT` sets the host port (`docker-compose.selfhost.yml`). Self-hosted calls are not x402-gated by default.

## Licence

MIT for the core engine. BSL-1.1 for the stealth/anti-detection module. See [LICENSE](LICENSE) and [LICENSE-BSL-STEALTH](LICENSE-BSL-STEALTH). Copyright (c) 2026 Rug Munch Media LLC.

## Where the numbers come from

| Claim | Source |
|---|---|
| 99 tools, 33 categories | `pry_mcp/tools/` (`PRY_TOOLS`), `llms.txt` |
| 15 tiers | `_tier_*` methods in `src/pry/engine/tiers_*.py` |
| 110 templates | `src/pry/commerce/templates/*.json` |
| 112 actors | `actor_factory/actors/` (directories) |
| 7 payment networks | `SUPPORTED_NETWORKS`, `src/pry/payments/x402/scheme/networks.py` |
| 377 test files | `tests/**/test_*.py` |

More: [Quickstart](docs/QUICKSTART.md) · [Concepts](docs/CONCEPTS.md) · [Testing](docs/ops/TESTING.md) · [Tool catalog](docs/ops/TOOLS-CATALOG.md) · [API reference](docs/ops/API-REFERENCE.md) · [Payments](docs/ops/PAYMENTS.md)
