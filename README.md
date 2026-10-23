# Pry — open any website

> Self-hosted web scraping and browser automation with Cloudflare bypass, an MCP server and x402 pay-per-call.

**License:** [MIT + BSL 1.1](LICENSE) · **Canonical:** https://git.rugmunch.io/RugMunchMedia/pryscraper
**Mirrors:** [GitHub](https://github.com/Rug-Munch-Media-LLC) · [GitLab](https://gitlab.com/rug-munch-media-group) · [Codeberg](https://codeberg.org/RugMunchMedia)

<img src="website/static/img/pry-logo.png" alt="Pry logo" width="360">


## What it is

Pry turns a URL into Markdown, structured JSON, or a screenshot. It escalates through 15 anti-bot tiers only as far as a site needs, then remembers which tier worked for that domain.

## Why it is different

- **One engine, three doors.** REST, CLI and the MCP surface resolve to the same scraper. `pry_mcp/tool_routes.py` maps every MCP tool to an HTTP route.
- **Escalation is learned per domain.** The engine records which tier succeeded and prefers it next time (`src/pry/engine/resilience.py`, `src/pry/engine/tier_score.py`).
- **Payment is per request.** An unpaid call returns HTTP 402 with the price and payee; the client pays on-chain and retries. No account, no subscription (`src/pry/payments/x402/`).

## 30-second quickstart

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git && cd pryscraper
python3 -m pip install -e .
PRY_X402_ENABLED=false PRY_API_KEY=devkey pry serve    # http://127.0.0.1:8005
```

The `pryscraper-mcp` distribution is not on PyPI yet; install from the repository
(or use the Docker path in [QUICKSTART](docs/QUICKSTART.md)).

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

`metadata.markdown_quality` scores the cleaned Markdown from 0 to 100. It runs seven weighted checks: relative links, fenced-code languages, heading structure, stray HTML tables, images, boilerplate noise, and duplicate blocks. A low score means the page kept little readable content; raise the tier, or switch to `POST /v1/extract` for typed output. The per-check breakdown is `metadata.markdown_checks` (`src/pry/engine/markdown_quality.py`).

## What you can do

| Job | Endpoint | Request |
|---|---|---|
| Scrape one page | `POST /v1/scrape` | `{"url":"https://example.com"}` |
| Search the web | `POST /v1/search` | `{"query":"rust web frameworks","limit":5}` |
| Crawl a site | `POST /v1/crawl` | `{"url":"https://example.com","maxPages":10}` |
| Map a site's URLs | `POST /v1/map` | `{"url":"https://example.com","limit":50}` |
| Extract fields | `POST /v1/extract` | `{"url":"https://shop.example/p/1","fields":{"price":"Price in USD"}}` |
| Run a template | `POST /v1/templates/execute` | `{"template_id":"amazon_product","url":"https://amazon.com/dp/..."}` |

`/v1/search` returns ranked web results (`data.results[]` with `url`, `title`, `description`). It queries SearXNG and falls back to DuckDuckGo.

`/v1/map` returns same-origin URLs in `data.links`. It reads the sitemap when `ignoreSitemap` is false, and falls back to link extraction. The cap is 500.

Crawl returns `{"success":true,"data":{"id":"sync","url":"...","pages":[...]}}`. Extract returns the requested keys as JSON. Templates read from `src/pry/commerce/templates/` (110 files).

The MCP surface is callable at `/mcp/` (Streamable HTTP) or `/mcp/sse` (SSE). Discovery is keyless; execution needs an API key or an x402 payment.

## Pricing

| Operation | USD per call | Operation key |
|---|---:|---|
| Scrape one URL | $0.001 | `scrape` |
| Web search | $0.003 | `search` |
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

## Async jobs

Crawl runs synchronously unless you pass a `webhook`. With a webhook it returns a job id straight away:

```bash
POST /v1/crawl   {"url":"https://example.com","maxPages":10,"webhook":"https://example.com/hook"}
# -> {"success":true,"data":{"id":"crawl-7f3a","status":"pending"}}
```

Poll `GET /v1/crawl/{id}` for status and the completed pages. `DELETE /v1/crawl/{id}` cancels a queued or running job, and repeating it is safe. `GET /v1/crawl/{id}/errors` lists per-URL failures. A finished job also posts its body to the webhook.

## Self-host

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
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
| MCP tools, 33 categories | `pry_mcp/tools/` (`PRY_TOOLS`), `llms.txt` |
| 15 tiers | `_tier_*` methods in `src/pry/engine/tiers_*.py` |
| 110 templates | `src/pry/commerce/templates/*.json` |
| 112 actors | `actor_factory/actors/` (directories) |
| 7 payment networks | `SUPPORTED_NETWORKS`, `src/pry/payments/x402/scheme/networks.py` |
| 377 test files | `tests/**/test_*.py` |

More: [Quickstart](docs/QUICKSTART.md) · [Concepts](docs/CONCEPTS.md) · [Testing](docs/ops/TESTING.md) · [Tool catalog](docs/ops/TOOLS-CATALOG.md) · [API reference](docs/ops/API-REFERENCE.md) · [Payments](docs/ops/PAYMENTS.md)
