# Pry

**Scrape any URL. Pay per call. Or self-host it.**

Pry turns a URL into Markdown, structured JSON, or a screenshot. It escalates through 15 anti-bot tiers only as far as a site needs, then remembers which tier worked for that domain.

## Quick start

### MCP client

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/"
    }
  }
}
```

Discovery is keyless. A paid `tools/call` needs an x402 payment or an API key. 99 tools are available immediately.

### Self-hosted

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
cp .env.selfhost.example .env.selfhost
./scripts/selfhost-init.sh
PRY_SELFHOST_PORT=8005 docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost up -d
```

API `http://localhost:8005` · MCP `http://localhost:8005/mcp/` · health `http://localhost:8005/health`.

### CLI

```bash
pip install pryscraper-mcp
PRY_X402_ENABLED=false PRY_API_KEY=devkey pry serve
pry open https://example.com
pry crawl https://docs.com --max-pages 20
```

## The shape of a request

```
client ──POST /v1/scrape──▶ auth + x402 gate
                                  │ unpaid → 402 with price and payee
                                  ▼ paid
                            tier chain 1 → 15
                                  ▼
                         markdown / JSON response
```

## What you get

- **REST**: `/v1/scrape`, `/v1/crawl`, `/v1/map`, `/v1/extract`, `/v1/templates/execute`.
- **MCP**: 99 tools in 33 categories at `/mcp/` (Streamable HTTP) and `/mcp/sse` (SSE), plus stdio via `pry-mcp`.
- **Payments**: x402 on seven networks — Base, Ethereum, Arbitrum, Optimism, Polygon, Solana, TRON.
- **Library**: 110 scraper templates and 112 Apify actors.

## Prices

| Operation | USD per call |
|---|---:|
| Scrape one URL | $0.001 |
| Crawl up to 10 pages | $0.010 |
| Structured extraction | $0.005 |

Source: `X402_PRICING`, `src/pry/payments/x402/scheme/pricing/catalog.py`.

## Licence

MIT for the core engine. BSL-1.1 for the stealth/anti-detection module. See [LICENSE](https://codeberg.org/RugMunchMedia/pryscraper/blob/main/LICENSE) and [LICENSE-BSL-STEALTH](https://codeberg.org/RugMunchMedia/pryscraper/blob/main/LICENSE-BSL-STEALTH).

Next: [Quickstart](quickstart) · [Configuration](configuration) · [API reference](api/scrape) · [x402](x402/overview).
