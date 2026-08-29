<div align="center">

# Pry — Open any website

**Self-hosted web scraping & browser automation API with native x402 micropayments**

[![CI](https://git.rugmunch.io/RugMunchMedia/pryscraper/badges/workflows/ci.yml/badge.svg)](https://git.rugmunch.io/RugMunchMedia/pryscraper/actions)
[![Tests](https://img.shields.io/badge/tests-162%2B_passing-brightgreen)](https://git.rugmunch.io/RugMunchMedia/pryscraper)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![x402](https://img.shields.io/badge/payments-x402%20%2F%20USDC%20%2F%20SOL%20%2F%20TRX-blueviolet)](https://docs.x402.org/)
[![MCP](https://img.shields.io/badge/MCP-73_tools-purple)](https://modelcontextprotocol.io/)

**15-tier anti-bot bypass** · Cloudflare, DataDome, Akamai · **Pay-per-call API** via crypto · **73 MCP tools** · **Runs as an Apify Actor**

[Quickstart](#quickstart) · [MCP Server](#mcp-server) · [x402 Payments](#x402-payments) · [Self-host](#docker) · [Registry Listings](#registry-listings) · [FAQ](docs/FAQ.md)

</div>

---

## Why Pry

Every scraper breaks the moment a site turns on Cloudflare. Pry routes each
request through an adaptive **15-tier fallback chain** — plain HTTP, TLS
fingerprinting, cloudscraper, FlareSolverr, undetected-chromedriver,
Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, cached
copies, AI visual scraping, mobile app API, and GraphQL discovery — escalating
only as far as the target actually requires, then remembering what worked per
domain.

### For AI Agents (MCP)

Pry exposes **73 MCP tools** across 33 categories — web scraping, data extraction,
monitoring, sports betting, legal intelligence, real estate, jobs, research, and more.
Every tool has structured input/output schemas, annotations (`readOnlyHint`,
`destructiveHint`, `idempotentHint`), and bot-readable descriptions.

**MCP URL:** `https://api.pryscraper.com/mcp/` (no account or API key needed to discover; paid calls gated by x402)

### For Humans (REST API)

```bash
# Scrape any URL (bypasses Cloudflare automatically)
curl -X POST https://api.pryscraper.com/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Response: 402 Payment Required (x402)
# Pay 0.001 USDC on Base → get your data
```

---

## Quickstart

### As an MCP Client (AI Agents)

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/"
    }
  }
}
```

That's it. No account or API key required to discover the server — each paid call is gated per-request via x402 (pay for what you use).

### Self-hosted (Docker)

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

API: `http://localhost:8002` · MCP: `http://localhost:8002/mcp/`

### CLI

```bash
pip install pryscraper-mcp
pry serve          # API on :8002
pry open https://example.com
pry crawl https://docs.com --max-pages 20
```

---

## MCP Server

### Tools (73 total, 33 categories)

| Category | Count | Example Tools |
|----------|:-----:|---------------|
| **Web Scraping** | 6 | `pry_scrape`, `pry_crawl`, `pry_screenshot`, `pry_template` |
| **Sports Betting** | 13 | `pry_odds`, `pry_arbitrage`, `pry_plus_ev`, `pry_live_odds` |
| **Legal** | 5 | `pry_legal_dockets`, `pry_legal_sec`, `pry_legal_sanctions` |
| **Government** | 3 | `pry_contracts`, `pry_grants`, `pry_procurement` |
| **Retail** | 4 | `pry_amazon_product`, `pry_walmart_product`, `pry_deals` |
| **Data Enrichment** | 2 | `pry_enrich`, `pry_domain` |
| **Search** | 2 | `pry_serp`, `pry_trends` |
| **Jobs & Careers** | 2 | `pry_jobs_list`, `pry_jobs_salary` |
| **Travel** | 2 | `pry_flights_grid`, `pry_hotel_rates` |
| **Social** | 3 | `pry_sentiment`, `pry_reviews`, `pry_tiktok_trending` |
| **Crypto** | 3 | `pry_token_launches`, `pry_token_security`, `pry_cex_listings` |
| **+ 16 more** | 18 | Events, energy, freight, grocery, patents, papers, weather... |

### Tool Example

```json
{
  "name": "pry_scrape",
  "description": "Scrape any URL to clean, readable markdown, automatically bypassing Cloudflare, DataDome, Akamai, and other anti-bot systems via a 15-tier fallback chain.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {"type": "string", "format": "uri"},
      "bypass_cloudflare": {"type": "boolean", "default": true},
      "js_render": {"type": "boolean", "default": false}
    },
    "required": ["url"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true
  }
}
```

### Transports

- **SSE** (Server-Sent Events): `https://api.pryscraper.com/sse`
- **Streamable HTTP**: `https://api.pryscraper.com/mcp/`
- **stdio**: `pry mcp --stdio`

---

## x402 Payments

Pry uses the [x402](https://docs.x402.org/) protocol for pay-per-call micropayments.
No accounts. No subscriptions. Pay only for what you use.

### Supported Networks

| Network | Assets | Your Wallet |
|---------|--------|-------------|
| **Base** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Ethereum** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Arbitrum** | USDC, USDT, ARB, ETH, WETH | `0x1E3AC...05C9` |
| **Optimism** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Polygon** | USDC, USDT, POL, WETH | `0x1E3AC...05C9` |
| **Solana** | USDC, USDT, SOL | `G1uZFfs...QyKv` |
| **TRON** | USDT, TRX | `TYSWXWr...E261p` |

### Pricing

| Operation | Price |
|-----------|-------|
| Single scrape | $0.001 |
| Crawl (per page) | $0.001 |
| AI extraction | $0.003 |
| Signup automation | $0.01 |
| CAPTCHA solving | $0.005 |

### How It Works

```
1. Client requests /v1/scrape
2. Server responds: 402 Payment Required
   {
     "x402Version": 1,
     "accepts": [{
       "scheme": "exact",
       "network": "eip155:8453",
       "maxAmountRequired": "1000",
       "asset": "USDC",
       "payToAddress": "0x1E3AC...05C9"
     }]
   }
3. Client sends payment (0.001 USDC on Base)
4. Client retries with PAYMENT-SIGNATURE header
5. Server verifies on-chain → returns data
```

---

## Registry Listings

Pry is listed on all major MCP marketplaces:

| Registry | Status | URL |
|----------|--------|-----|
| **Glama** | ⏳ Pending | https://glama.ai/mcp |
| **Smithery** | ⏳ Pending | https://smithery.ai |
| **MCP Registry** | ⏳ Pending | https://registry.modelcontextprotocol.io/ |
| **x402 Bazaar** | ⏳ Pending | https://x402.org/bazaar |
| **Coinbase CDP** | ⏳ Pending | https://cdp.coinbase.com/x402/bazaar |

### Discovery Endpoints

```
GET /.well-known/x402.json        → Payment manifest
GET /.well-known/agent.json       → AI agent card
GET /.well-known/x402-bazaar.json → Marketplace listing
GET /llms.txt                     → AI agent discovery (llms.txt standard)
```

---

## Comparison

| Feature | Pry | Firecrawl | Scrapling | Apify |
|---------|:---:|:---------:|:---------:|:-----:|
| Anti-detection tiers | **15** | 2 | 3 | 1 |
| MCP tools | **73** | 5 | 8 | 0 |
| x402 payments | ✅ | ❌ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ | ✅ |
| Templates | **110+** | 0 | 0 | 1000+ |
| AI visual scraping | ✅ | ❌ | ❌ | ❌ |
| GraphQL discovery | ✅ | ❌ | ❌ | ❌ |
| Mobile app API | ✅ | ❌ | ❌ | ❌ |
| Crypto payments | ✅ | ❌ | ❌ | ❌ |
| Price | Pay-per-use | $49-$499/mo | Free | $49+/mo |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Pry Platform                          │
├─────────────────────────────────────────────────────────────┤
│  MCP Layer (73 tools)  │  REST API  │  x402 Payments        │
├─────────────────────────────────────────────────────────────┤
│  15-Tier Scraping Engine                                    │
│  ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐  │
│  │Direct│TLS  │Cloud│Flare│Undet│Camou│Play │Google│Tor  │  │
│  │HTTP  │FP   │scrap│Solv │Chrom│fox  │wright│bot  │     │  │
│  └─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘  │
│  ┌─────┬─────┬─────┬─────┬─────┐                           │
│  │Prem │Arch │Cache│AI   │Mobile│                          │
│  │Proxy│ive  │     │Vis  │API   │                          │
│  └─────┴─────┴─────┴─────┴─────┘                           │
├─────────────────────────────────────────────────────────────┤
│  Data: 110+ templates · 20+ domains · 7 blockchain networks │
└─────────────────────────────────────────────────────────────┘
```

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Rug Munch Media LLC.

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://rugmunch.io">Rug Munch Media LLC</a> — sovereign payments for the agentic economy.</sub>
</div>
