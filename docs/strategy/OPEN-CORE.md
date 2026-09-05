# Open-Core Model

This repository is part of RugMunch's open-core product.

The code here is **fully functional open source** (MIT). You can self-host, modify, and contribute.

## What's Open Source (MIT, self-hostable)

- **Core scraping engine** — the 15-tier anti-bot bypass and fallback chain
- **MCP server framework** — how to build your own MCP server with x402 payments
- **x402 payment integration** — how to accept crypto pay-per-call
- **Site mapping + content filtering** — Firecrawl/Crawl4AI-style features
- **Basic data collection modules** — the `datasets/` framework
- **Actor factory framework** — how to build Apify actors. The FACTORY is OSS; our specific actors are NOT
- **Coffer facilitator** — the x402-coffer repo, a fully OSS payment facilitator

## What's Proprietary (ours, not in public repos)

- **Our 112 specific Apify actors and their configurations** — the factory is OSS, the products are ours
- **Our 104 specific MCP tool implementations** for sports betting, crypto, and prediction markets — the framework is OSS, the tools are ours
- **Sports betting intelligence modules** — sharp money, player intel, live analytics, weather impact, Kelly criterion, derivatives
- **Prediction market data modules** — Polymarket/Kalshi integration
- **Actor pricing strategy and PPE event definitions**
- **Internal infrastructure, deployment configs, operational methods**
- **Competitive intelligence and market analysis**

## The Principle

We give away the **platform**: how to build an x402 MCP server, how to build Apify actors, how to do anti-bot scraping.

We keep the **products**: our specific actors, our specific MCP tools, our sports betting intelligence.

Others can build their own MCP marketplaces using our OSS platform. They cannot copy our actor catalog or our sports betting tools.

## Managed Platform

RugMunch offers a **managed platform** at [rugmunch.io](https://rugmunch.io) that includes:
- One-click deployment
- Admin dashboard
- Enterprise SSO/RBAC
- Managed infrastructure
- Priority support

The admin panel, production infrastructure, and operational tooling are proprietary.

[Learn more](https://rugmunch.io/docs/open-core)
