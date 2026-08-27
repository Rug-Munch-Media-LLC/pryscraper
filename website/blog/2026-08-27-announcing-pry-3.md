---
slug: announcing-pry-3
title: Announcing Pry 3.0 — MCP-Native, Multi-Chain, Self-Hosted
authors:
  - name: Rug Munch Media
    title: Engineering Team
    url: https://rugmunch.io
tags: [release, mcp, x402, crypto]
---

Pry 3.0 is a complete rewrite focused on three things: **MCP-native tooling**, **multi-chain x402 payments**, and **self-hosted sovereignty**.

## What's New

### 73 MCP Tools
Pry now exposes 73 MCP tools across 27 categories — web scraping, data extraction, monitoring, sports betting, legal intelligence, real estate, jobs, research, and more. Every tool has structured input/output schemas and annotations.

### 15-Tier Fallback Chain
We expanded from 12 to 15 tiers with AI visual scraping (screenshot + LLM vision), mobile app API impersonation, and GraphQL API discovery.

### Multi-Chain x402 Payments
Pay-per-call micropayments on 7 networks: Base, Ethereum, Arbitrum, Optimism, Polygon, Solana, and TRON. No accounts. No subscriptions.

### Public MCP Access
AI agents can discover and use Pry without API keys. Well-known endpoints (`/.well-known/x402.json`, `/.well-known/agent.json`, `/llms.txt`) enable automatic discovery.

## Comparison

| Feature | Pry 3.0 | Firecrawl | Scrapling | Apify |
|---------|:-------:|:---------:|:---------:|:-----:|
| Anti-detection tiers | **15** | 2 | 3 | 1 |
| MCP tools | **73** | 5 | 8 | 0 |
| x402 payments | ✅ | ❌ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ | ✅ |

## Get Started

```bash
# MCP (AI agents)
{"mcpServers": {"pry": {"url": "http://100.104.130.92:8002/sse"}}}

# Docker (self-hosted)
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

## License

MIT — see [LICENSE](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/LICENSE).
