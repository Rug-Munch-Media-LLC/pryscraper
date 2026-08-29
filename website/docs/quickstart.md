# Quickstart

Get Pry running in under 5 minutes.

## Option 1: MCP Client (AI Agents)

Add Pry to your MCP client configuration:

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/sse"
    }
  }
}
```

All 73 tools are immediately available. No API key required.

## Option 2: Docker (Self-hosted)

```bash
# Clone the repo
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper

# Start the full stack
docker compose up -d
```

Services:
- Pry API: `http://localhost:8002`
- MCP SSE: `http://localhost:8002/sse`
- Dashboard: `http://localhost:8002/dashboard`
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
curl -X POST http://localhost:8002/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Response: 402 with x402 payment instructions
# Pay 0.001 USDC on Base → retry with PAYMENT-SIGNATURE → get data
```

## Next Steps

- [Installation Guide](installation) — detailed setup options
- [Configuration](configuration) — env vars, wallets, networks
- [API Reference](../api/scrape) — full endpoint documentation
- [x402 Payments](../x402/overview) — payment integration guide
- [MCP Server](../mcp/overview) — AI agent integration
