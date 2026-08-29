# Pry Scraping API

**Pay-per-request HTTP for the multi-chain economy**

Pry is a self-hosted web scraping and browser automation platform with native x402 micropayments. It routes each request through an adaptive **15-tier fallback chain** — direct HTTP, TLS fingerprinting, cloudscraper, FlareSolverr, undetected-chromedriver, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, cached copies, AI visual scraping, mobile app API, and GraphQL discovery.

## Quick Start

### As an MCP Client (AI Agents)

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/sse"
    }
  }
}
```

That's it. No API key. 73 tools immediately available.

### Self-hosted (Docker)

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

### CLI

```bash
pip install pryscraper-mcp
pry serve          # API on :8002
pry open https://example.com
pry crawl https://docs.com --max-pages 20
```

## Why Pry?

| Feature | Pry | Firecrawl | Scrapling | Apify |
|---------|:---:|:---------:|:---------:|:-----:|
| Anti-detection tiers | **15** | 2 | 3 | 1 |
| MCP tools | **73** | 5 | 8 | 0 |
| x402 payments | ✅ | ❌ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ | ✅ |
| Templates | **110+** | 0 | 0 | 1000+ |
| Price | Pay-per-use | $49-$499/mo | Free | $49+/mo |

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

## License

MIT — see [LICENSE](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/LICENSE).
