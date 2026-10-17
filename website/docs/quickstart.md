# Quickstart

Get Pry running in under 5 minutes.

## Option 1: MCP Client (AI Agents)

Add Pry to your MCP client configuration:

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8005/sse"
    }
  }
}
```

All 99 tools are immediately available. Bearer auth is only enforced when `PRY_API_KEY` is set (loopback-only by default).

## Option 2: Docker (Self-hosted)

```bash
# Clone the repo
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper

# Start the full stack (host port 8005, container port 8002)
docker compose up -d
```

Services:
- Pry API: `http://localhost:8005`
- MCP SSE: `http://localhost:8005/sse`
- Dashboard: `http://localhost:8005/dashboard`
- FlareSolverr: `http://localhost:8191`

## Option 3: CLI

```bash
# Install
pip install pryscraper-mcp

# Serve
pry serve

# Scrape a URL
pry open https://example.com

# Crawl a website
pry crawl https://docs.com --max-pages 20

# Extract structured data
pry extract https://example.com/products --schema product.json
```

## Option 4: REST API

```bash
# Scrape (returns 402 Payment Required)
curl -X POST http://localhost:8005/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Response: 402 with x402 payment instructions
# Pay 0.001 USDC on Base → retry with PAYMENT-SIGNATURE → get data
```

## Option 5: Python SDK (x402-aware)

The SDK handles the 402 for you: it parses `accepts[]`, calls your `pay`
callback, then retries the same request once with the payment header.

```python
import asyncio
from pry.api.pry_sdk import PryCrawl, PaymentRequired


async def main():
    client = PryCrawl(
        "http://localhost:8005", api_key="pry_..."
    )  # hosted: https://api.pryscraper.com
    try:
        return await client.scrape("https://example.com")  # 200
    except PaymentRequired as exc:  # 402 challenge
        return await client.scrape("https://example.com", pay=lambda c: sign(c))


page = asyncio.run(main())
print(page["data"]["markdown"][:200])
```

Typed failures raise `PryError(status, code, detail)` parsed from the RFC-7807
body. `max_price_usd=` refuses expensive challenges, `max_retries=` tunes
GET retries on 429/5xx, and `client.iter_pages("/v1/templates")` paginates list
endpoints.

## Next Steps

- [Installation Guide](installation) — detailed setup options
- [Configuration](configuration) — env vars, wallets, networks
- [API Reference](api/scrape) — full endpoint documentation
- [x402 Payments](x402/overview) — payment integration guide
- [MCP Server](mcp/overview) — AI agent integration
