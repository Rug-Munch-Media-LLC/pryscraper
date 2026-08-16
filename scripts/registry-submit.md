# Pry MCP — Registry Submission Guide

SPDX-License-Identifier: MIT · Copyright (c) 2026 Rug Munch Media LLC

How to submit Pry to the MCP registries, with the exact payloads. This file is
the operator's runbook; it must be kept in sync with `server.json`, `SKILL.md`,
and `llms.txt` (the metadata sources of truth).

## Current metadata (v3.0.0 — 19 tools)

| Field | Value |
|---|---|
| Registry identity | `io.rugmunch/pry` |
| Title | Pry — Web Scraping & Browser Automation MCP |
| Version | 3.0.0 |
| Website | https://pryscraper.com |
| PyPI distribution | `pryscraper-mcp` (see `pyproject.toml`; local name `pry` preserved) |
| Install | `uvx pryscraper-mcp` or `pipx install pryscraper && pry-mcp` |
| Transport | stdio (`pry-mcp`) + streamable HTTP `https://pryscraper.com/mcp` |
| Tool count | **19** = 15 core tools + **4 marketplace tools** |

Tool set (names must match `pry_mcp/tools.py` exactly):

```
pry_scrape           pry_crawl            pry_extract
pry_template         pry_search_templates pry_monitor
pry_compliance       pry_enrich           pry_parse_document
pry_screenshot       pry_x402_pricing     pry_referrals
pry_token_launches   pry_cex_listings     pry_token_security   (crypto)
pry_amazon_product   pry_amazon_search    (marketplace)
pry_walmart_product  pry_tiktok_trending  (marketplace)
```

> The 4 marketplace tools were added in v3.0.0. If the registry you are
> submitting to is still showing 15 tools, bump/refresh the listing after this
> release. `glama.json` and `pulsemcp.json` in the repo root are **stale**
> (they list 8 tools and old URLs) — refresh them before/at submission.
> [REVIEW] — decide whether to retire those two files in favor of server.json.

## Consistency checks before any submission

Run from the repo root:

```bash
# 1. Tool list in server.json == tools registered by the MCP server
python -c "import json; s=json.load(open('server.json')); import sys; sys.path.insert(0,'.'); from pry_mcp.tools import PRY_TOOLS; a={t['name'] for t in s['tools']}; b={t['name'] for t in PRY_TOOLS}; assert a==b, (a^b); print('tools OK:', len(a))"

# 2. Version consistent
python -c "import tomllib,json; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'], json.load(open('server.json'))['version'])"

# 3. Docs mention the same count (grep '19 MCP tools' / '19 tools')
grep -c "19" SKILL.md llms.txt README.md
```

## 1. Official MCP registry (registry.modelcontextprotocol.io)

The official registry accepts the [server.json schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json).

Exact steps:
1. Open https://registry.modelcontextprotocol.io/ and sign in with the Rug Munch
   GitHub account (`cryptorugmuncher`).
2. Choose **Add Server** → **Import from server.json**.
3. Paste the payload below (or point at this repo's `server.json` — the schema
   identifier is already in the file).
4. Verify the auto-detected fields: name `io.rugmunch/pry`, packages
   `pypi:pryscraper-mcp` (v3.0.0, stdio), remotes `https://pryscraper.com/mcp`.
5. The registry will fetch the tool list from the server's
   `tools/list` — confirm 19 tools appear.
6. Submit; keep `server.json` in sync on every release.

### server.json payload (current)

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.rugmunch/pry",
  "title": "Pry — Web Scraping & Browser Automation MCP",
  "description": "Self-hosted web scraping MCP: scrape, crawl, extract, monitor, parse, screenshot, marketplace intelligence, x402 pricing.",
  "version": "3.0.0",
  "websiteUrl": "https://pryscraper.com",
  "repository": {
    "source": "codeberg",
    "url": "https://codeberg.org/cryptorugmunch/pryscraper"
  },
  "packages": [
    {
      "registryType": "pypi",
      "identifier": "pryscraper-mcp",
      "version": "3.0.0",
      "transport": { "type": "stdio" }
    }
  ],
  "remotes": [
    { "type": "streamable-http", "url": "https://pryscraper.com/mcp" }
  ],
  "tools": [
    { "name": "pry_scrape", "description": "Scrape any URL to clean markdown with a 9-tier anti-bot fallback chain (Cloudflare bypass)." },
    { "name": "pry_crawl", "description": "Crawl a website from a seed URL, discovering and scraping linked pages up to max_pages." },
    { "name": "pry_extract", "description": "Extract structured JSON from a URL using CSS selectors — cheaper than LLM extraction." },
    { "name": "pry_template", "description": "Execute one of 110+ pre-built scraper templates (amazon, walmart, linkedin, etc.)." },
    { "name": "pry_search_templates", "description": "Search the scraper template catalog by keyword, category, or site name." },
    { "name": "pry_monitor", "description": "Create a content-change monitor that notifies via webhook, Slack, or Discord." },
    { "name": "pry_compliance", "description": "Score scraping legal risk from robots.txt, ToS, GDPR/CCPA, and PII exposure." },
    { "name": "pry_enrich", "description": "Enrich a URL with company info, tech stack detection, and social profiles." },
    { "name": "pry_parse_document", "description": "Parse a document (PDF, DOCX, image) and extract its text and tables." },
    { "name": "pry_screenshot", "description": "Take a full-page screenshot of a URL and return it as a base64-encoded PNG." },
    { "name": "pry_x402_pricing", "description": "Get current x402 pay-per-call pricing in USDC atomic units per tool." },
    { "name": "pry_referrals", "description": "Get Pry's referral catalog — 60+ providers with revenue-attribution links." },
    { "name": "pry_token_launches", "description": "Track recent token launches, deployer activity, and new mint intelligence (crypto)." },
    { "name": "pry_cex_listings", "description": "Monitor CEX listing announcements and delisting events for crypto tokens (crypto)." },
    { "name": "pry_amazon_product", "description": "Look up a single Amazon product by ASIN — live price, title, availability, rating (marketplace)." },
    { "name": "pry_amazon_search", "description": "Search Amazon by keyword and return matching listings with price, rating, ASIN (marketplace)." },
    { "name": "pry_walmart_product", "description": "Look up a single Walmart product by product ID — price, title, seller, rating (marketplace)." },
    { "name": "pry_tiktok_trending", "description": "Get currently trending TikTok Shop products by engagement and sales velocity (marketplace)." },
    { "name": "pry_token_security", "description": "Run token security checks — honeypot, mint authority, LP lock, holder distribution (crypto)." }
  ]
}
```

## 2. mcp.so

Exact steps:
1. Go to https://mcp.so and sign in (GitHub OAuth).
2. **Submit Server** → paste the same `server.json` payload (mcp.so accepts the
   MCP server.json format).
3. Set the package URL to https://pypi.org/project/pryscraper-mcp/ once the
   first release is live, and the homepage to https://pryscraper.com.
4. Tags: `web-scraping`, `browser-automation`, `x402`, `anti-bot`,
   `marketplace-intelligence`, `crypto`.
5. Re-submit or open a metadata-update PR whenever the tool list changes
   (mcp.so scrapes `tools/list`, so a live endpoint helps).

## 3. Glama (glama.ai)

Glama has a [server.json schema](https://glama.ai/mcp/schema.json) — the repo
root already has `glama.json` (currently **stale**: 8 tools, old GitHub URLs).

Exact steps:
1. Update `glama.json` from `server.json` (19 tools, `pypi:pryscraper-mcp`
   install, homepage https://pryscraper.com) — or delete it and let Glama pull
   the official registry entry.
2. Go to https://glama.ai/mcp/servers → **Add server** → paste the payload.
3. Confirm the transports: stdio command `pryscraper-mcp` and
   streamable-http `https://pryscraper.com/mcp`.
4. Glama shows an "MCP compliance" score; a reachable `/mcp` endpoint plus
   `tools/list` returning 19 tools maximizes it.

## 4. Secondary registries (optional)

- **PulseMCP** (`pulsemcp.json` in repo root — also stale, update like Glama):
  https://www.pulsemcp.com/submit
- **Smithery** (`smithery.yaml`): https://smithery.ai — keep the
  `startCommand` pointing at `pryscraper-mcp`.

## Post-submission checklist

- [ ] First `pryscraper-mcp` release live on PyPI (`bash scripts/publish.sh`)
- [ ] server.json == pry_mcp/tools.py (19 tools)
- [ ] Official registry listing shows 19 tools
- [ ] mcp.so + Glama listings refreshed
- [ ] `glama.json` / `pulsemcp.json` updated or retired
