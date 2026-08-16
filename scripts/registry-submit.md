# Pry MCP — Registry Submission Guide

SPDX-License-Identifier: MIT · Copyright (c) 2026 Rug Munch Media LLC

How to submit Pry to the MCP registries, with the exact payloads. This file is
the operator's runbook; it must be kept in sync with `server.json`, `glama.json`,
`pulsemcp.json`, `smithery.yaml`, `SKILL.md`, and `llms.txt` (the metadata
sources of truth). **Source of truth for the tool list: `pry_mcp/tools.py`
(`PRY_TOOLS`) — 35 tools as of v3.0.0.**

## Current metadata (v3.0.0 — 35 tools)

| Field | Value |
|---|---|
| Registry identity | `io.rugmunch/pry` |
| Title | Pry — Web Scraping, Browser Automation & Data Intelligence MCP |
| Version | 3.0.0 |
| Website | https://pryscraper.com |
| PyPI distribution | `pryscraper-mcp` (see `pyproject.toml`; local name `pry` preserved) |
| Install | `uvx pryscraper-mcp` or `pipx install pryscraper && pry-mcp` |
| Transport | stdio (`pryscraper-mcp` / `pry-mcp` console scripts) + streamable HTTP `https://pryscraper.com/mcp` |
| Tool count | **35** = 15 core tools + 20 data-domain tools (crypto ×3, marketplace ×4, legal ×3, real estate ×1, jobs ×2, travel ×2, attention ×2, local ×2, gov ×2, ip ×2) |

Tool set (names must match `pry_mcp/tools.py` exactly — the consistency check
below enforces this):

```
Core (15):
pry_scrape            pry_crawl            pry_extract
pry_template          pry_search_templates pry_monitor
pry_compliance        pry_enrich           pry_parse_document
pry_screenshot        pry_x402_pricing     pry_referrals

Crypto (3):
pry_token_launches    pry_cex_listings     pry_token_security

Marketplace (4):
pry_amazon_product    pry_amazon_search    pry_walmart_product
pry_tiktok_trending

Legal (3):
pry_legal_dockets     pry_legal_sec        pry_legal_sanctions

Real estate (1):
pry_realestate_search

Jobs (2):
pry_jobs_list         pry_jobs_salary

Travel (2):
pry_flights_grid      pry_hotel_rates

Attention (2):
pry_serp              pry_trends

Local (2):
pry_places_search     pry_reviews

Gov (2):
pry_procurement       pry_recalls

IP (2):
pry_patents           pry_trademarks
```

> The data-domain tools were added across the v3.0.0 development cycle (legal,
> real estate, travel → jobs/attention/local → gov/ip). If a registry you
> submitted to earlier is still showing 15–27 tools, bump/refresh the listing
> after this release. `server.json` is the canonical registry payload;
> `glama.json` and `pulsemcp.json` are derived from it and must stay in sync.

## Consistency checks before any submission

Run from the repo root:

```bash
# 1. Tool list in every metadata file == tools registered by the MCP server
python -c "
import json, sys
sys.path.insert(0, '.')
from pry_mcp.tools import PRY_TOOLS
expected = {t['name'] for t in PRY_TOOLS}
for f, key in [('server.json','tools'), ('glama.json','tools'), ('pulsemcp.json','tools')]:
    data = json.load(open(f))
    got = {t['name'] if isinstance(t, dict) else t for t in data[key]}
    assert got == expected, (f, sorted(expected-got), sorted(got-expected))
    print(f, 'OK', len(got))
print('PRY_TOOLS', len(expected))
"

# 2. Version consistent across pyproject.toml + all metadata
python -c "
import tomllib, json
v = tomllib.load(open('pyproject.toml','rb'))['project']['version']
for f in ['server.json', 'glama.json', 'pulsemcp.json']:
    assert json.load(open(f))['version'] == v, f
print('version OK:', v)
"

# 3. Docs mention the same count (expect '35' in each)
grep -l "35" SKILL.md llms.txt README.md
```

## CLI-submittable vs manual-dashboard

| Registry | How to submit | Auth required | Status |
|---|---|---|---|
| Official MCP registry (registry.modelcontextprotocol.io) | **Manual dashboard** — Import from server.json | GitHub login (`cryptorugmuncher`) | Not submitted yet |
| mcp.so | **Manual dashboard** — Submit Server, paste server.json | GitHub OAuth | Not submitted yet |
| Glama (glama.ai) | **Manual dashboard** — Add server, paste glama.json | GitHub OAuth | Not submitted yet |
| Smithery (smithery.ai) | **Manual dashboard** — deploy from `smithery.yaml` | GitHub OAuth | Not submitted yet |
| PulseMCP (pulsemcp.com) | **Manual dashboard** — Submit MCP server | GitHub OAuth | Not submitted yet |
| PyPI (pypi.org) | **CLI** — `bash scripts/publish.sh` (twine) | PyPI API token (`PRY_PYPI_TOKEN` / gopass `pry/pypi_token`) | Needs token |

There is **no official CLI** for the MCP server registries yet — all five
registries above are dashboard-driven with GitHub OAuth. The only
CLI-submittable artifact is the PyPI package, which the official registry,
mcp.so, Glama, and PulseMCP all reference by identifier (`pypi:pryscraper-mcp`),
so **publish to PyPI first**; the registries can then auto-resolve install
metadata.

## 1. Official MCP registry (registry.modelcontextprotocol.io)

The official registry accepts the [server.json schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json).

Exact steps (manual dashboard):
1. Open https://registry.modelcontextprotocol.io/ and sign in with the Rug Munch
   GitHub account (`cryptorugmuncher`).
2. Choose **Add Server** → **Import from server.json**.
3. Paste the payload from the repo root `server.json` (the schema identifier is
   already in the file — the payload below is a verbatim copy).
4. Verify the auto-detected fields: name `io.rugmunch/pry`, packages
   `pypi:pryscraper-mcp` (v3.0.0, stdio), remotes `https://pryscraper.com/mcp`.
5. The registry will fetch the tool list from the server's `tools/list` —
   confirm **35** tools appear.
6. Submit; keep `server.json` in sync on every release.

### server.json payload (current — verbatim from repo root)

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.rugmunch/pry",
  "title": "Pry — Web Scraping, Browser Automation & Data Intelligence MCP",
  "description": "Self-hosted web intelligence MCP: scrape, crawl, extract, monitor, parse, screenshot, x402 pricing, plus ten data domains (crypto, marketplace, legal, real estate, jobs, travel, attention, local, gov, ip).",
  "version": "3.0.0",
  "websiteUrl": "https://pryscraper.com",
  "repository": { "source": "codeberg", "url": "https://codeberg.org/cryptorugmunch/pryscraper" },
  "packages": [
    { "registryType": "pypi", "identifier": "pryscraper-mcp", "version": "3.0.0", "transport": { "type": "stdio" } }
  ],
  "remotes": [ { "type": "streamable-http", "url": "https://pryscraper.com/mcp" } ],
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
    { "name": "pry_token_security", "description": "Run token security checks — honeypot, mint authority, LP lock, holder distribution (crypto)." },
    { "name": "pry_amazon_product", "description": "Look up a single Amazon product by ASIN — live price, title, availability, rating (marketplace)." },
    { "name": "pry_amazon_search", "description": "Search Amazon by keyword and return matching listings with price, rating, ASIN (marketplace)." },
    { "name": "pry_walmart_product", "description": "Look up a single Walmart product by product ID — price, title, seller, rating (marketplace)." },
    { "name": "pry_tiktok_trending", "description": "Get currently trending TikTok Shop products by engagement and sales velocity (marketplace)." },
    { "name": "pry_legal_dockets", "description": "Search U.S. federal and state court dockets by full-text query via CourtListener (legal)." },
    { "name": "pry_legal_sec", "description": "Search SEC EDGAR filings by ticker and form type — filing dates, forms, accession numbers (legal)." },
    { "name": "pry_legal_sanctions", "description": "Screen a person or entity against the OFAC SDN sanctions list (legal)." },
    { "name": "pry_realestate_search", "description": "Search real-estate listings by location and status — price, beds/baths, sqft (real estate)." },
    { "name": "pry_jobs_list", "description": "List ATS job postings for a company — Greenhouse, Lever, Ashby, Workday (jobs)." },
    { "name": "pry_jobs_salary", "description": "Get per-level salary bands (total comp, base, stock, bonus) from Levels.fyi (jobs)." },
    { "name": "pry_flights_grid", "description": "Cheapest flight per day over a date range for an origin/destination pair (travel)." },
    { "name": "pry_hotel_rates", "description": "Per-night hotel rates for a stay window — Google Hotels with Booking.com fallback (travel)." },
    { "name": "pry_serp", "description": "Scrape a Google SERP — organic results, AI Overview, People Also Ask (attention)." },
    { "name": "pry_trends", "description": "Google Trends interest over time plus related queries (attention)." },
    { "name": "pry_places_search", "description": "Search Google Maps for local businesses — name, rating, address, place IDs (local)." },
    { "name": "pry_reviews", "description": "Full review history for a place from Google Maps or Yelp, beyond the 5-review cap (local)." },
    { "name": "pry_procurement", "description": "Search U.S. federal procurement opportunities from SAM.gov (gov)." },
    { "name": "pry_recalls", "description": "Search recent CPSC/FDA product recalls (gov)." },
    { "name": "pry_patents", "description": "Search U.S. patents by keyword via USPTO/Google Patents (ip)." },
    { "name": "pry_trademarks", "description": "Search U.S. trademarks by keyword or owner via USPTO (ip)." }
  ]
}
```

> `glama.json` and `pulsemcp.json` are derived from this payload. Regenerate
> them after any tool-list change: same 35 tool names, `io.rugmunch/pry` name,
> homepage https://pryscraper.com, repository https://codeberg.org/cryptorugmunch/pryscraper.

## 2. mcp.so

Exact steps (manual dashboard):
1. Go to https://mcp.so and sign in (GitHub OAuth).
2. **Submit Server** → paste the same `server.json` payload (mcp.so accepts the
   MCP server.json format).
3. Set the package URL to https://pypi.org/project/pryscraper-mcp/ once the
   first release is live, and the homepage to https://pryscraper.com.
4. Tags: `web-scraping`, `browser-automation`, `x402`, `anti-bot`,
   `marketplace-intelligence`, `crypto`, `legal`, `real-estate`, `jobs`,
   `travel`, `seo`, `local-business`, `government-data`, `ip`.
5. Re-submit or open a metadata-update PR whenever the tool list changes
   (mcp.so scrapes `tools/list`, so a live endpoint helps).

## 3. Glama (glama.ai)

Glama has a [server.json schema](https://glama.ai/mcp/schema.json) — the repo
root already has `glama.json` (kept in sync with `server.json`: 35 tools,
`io.rugmunch/pry`, stdio `pryscraper-mcp` + streamable-http
`https://pryscraper.com/mcp`).

Exact steps (manual dashboard):
1. Go to https://glama.ai/mcp/servers → **Add server** → paste the `glama.json`
   payload (or import the official registry entry once it is live).
2. Confirm the transports: stdio command `pryscraper-mcp` and
   streamable-http `https://pryscraper.com/mcp`.
3. Glama shows an "MCP compliance" score; a reachable `/mcp` endpoint plus
   `tools/list` returning 35 tools maximizes it.

## 4. Smithery (smithery.ai)

Smithery deploys the server from `smithery.yaml` (repo root) — it does **not**
use the server.json registry payload. The YAML defines the build command
(`pip install -e ".[dev]"`) and the start command (`python3 -m mcp_production`
with `PRY_API_URL`/`PRY_API_KEY` config). Smithery fetches the live tool list
from `tools/list` at deploy time.

Exact steps (manual dashboard):
1. Go to https://smithery.ai → **Sign in** (GitHub OAuth).
2. **Create Server** → **Import from GitHub** → select
   `cryptorugmunch/pryscraper` (or paste `smithery.yaml`).
3. Smithery builds the container from `buildCommand` and runs
   `startCommand`; verify the deployed health endpoint and that
   `tools/list` returns 35 tools.
4. Keep the comment in `smithery.yaml` (identity `io.rugmunch/pry`, 35 tools)
   in sync with `PRY_TOOLS` on every release.

## 5. PulseMCP (pulsemcp.com)

Exact steps (manual dashboard):
1. Go to https://www.pulsemcp.com/submit and sign in (GitHub OAuth).
2. Paste the `pulsemcp.json` payload (35 tools, `io.rugmunch/pry`, pip install
   `pryscraper-mcp` → command `pryscraper-mcp`).
3. Set homepage https://pryscraper.com and repository
   https://codeberg.org/cryptorugmunch/pryscraper.
4. Categories: Web Scraping, Browser Automation, Data Extraction, Market
   Intelligence, Legal & Compliance, Real Estate, Jobs & Careers, Travel,
   SEO & Attention.

## Post-submission checklist

- [ ] First `pryscraper-mcp` release live on PyPI (`bash scripts/publish.sh`)
- [ ] server.json == pry_mcp/tools.py (35 tools)
- [ ] glama.json + pulsemcp.json regenerated from server.json (35 tools)
- [ ] Official registry listing shows 35 tools
- [ ] mcp.so + Glama + Smithery + PulseMCP listings refreshed
- [ ] SKILL.md / README.md / llms.txt mention the 35-tool count
