---
title: Pry Architecture & Design
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-06-30
audience:
  - engineers
  - agents
note: Replaces Firecrawl, Crawl4AI, and Browserless in a single self-hosted application.
---

# Pry Architecture

## Overview

Pry (formerly MunchCrawl) v3.0.0 is a self-hosted web scraping + browser automation API.
It replaces Firecrawl, Crawl4AI, and Browserless in a single application. No API keys needed.

**Stack**: Python 3.11+, FastAPI, Playwright, FlareSolverr, Redis, httpx
**Entry**: `cli.py:main()` → CLI or `api.py:app` → FastAPI
**Deployment**: Docker Compose (recommended) or bare metal

## Scraping Pipeline (10-tier fallback)

```
Client → Pry API → Ultimate Scraper → 10-tier fallback chain
```

| Tier | Method | Purpose |
|------|--------|---------|
| 1 | Direct HTTP | Rotating UAs, browser-like headers |
| 2 | cloudscraper | Python-native Cloudflare JS challenge |
| 3 | FlareSolverr | Headless Chrome Cloudflare/WAF bypass |
| 4 | undetected-chromedriver | Modified Chrome, no automation flags |
| 5 | Playwright | Full browser with human behavior (mouse, scroll, timing) |
| 6 | Googlebot UA | Search engine crawl mimic |
| 7 | Tor proxy | Anonymous routing via SOCKS5 |
| 8 | Archive.org / Wayback Machine | Cached version fallback |
| 9 | Google Cache | Cached snapshot |
| 10 | Textise dot iitty | Text-only version |

## Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│   CLI/SDK    │───→│  Pry API      │───→│  Ultimate Scraper │
│  (httpx)     │    │  (FastAPI)    │    │  (10-tier chain) │
└──────────────┘    └──────┬───────┘    └────────┬─────────┘
                           │                      │
                      ┌────┴────┐           ┌─────┴──────┐
                      │  Cache  │           │  Playwright │
                      │  Redis  │           │  FlareSolv. │
                      │  Rate   │           │  cloudscraper│
                      │  Limit  │           │  Tor/SOCKS5 │
                      └─────────┘           └────────────┘
                           │                      │
                      ┌────┴────┐           ┌─────┴──────┐
                      │  MCP    │           │  Parse/     │
                      │  Server  │           │  Extract    │
                      └─────────┘           └────────────┘
```

## Database & Storage

All data stored under `~/.pry/`:

| Directory | Purpose |
|-----------|---------|
| `~/.pry/quality/` | Quality check history |
| `~/.pry/reviews/` | Human review queue |
| `~/.pry/intel/` | Competitive intelligence snapshots |
| `~/.pry/costing/` | Usage tracking |
| `~/.pry/freshness/` | Content fingerprints |
| `~/.pry/structure/` | Page structure monitor history |
| `~/.pry/seo/` | SEO snapshot history |
| `~/.pry/monitors/` | Scheduled monitors |
| `~/.pry/vault/` | Encrypted credentials |
| `~/.pry/accounts/` | Registered account pool |
| `~/.pry/reports/` | Generated client reports |
| `~/.pry/training/` | AI training datasets |
| `~/.pry/pipelines/` | Saved pipeline definitions |
| `~/.pry/gdpr/` | Consent records, deletion requests |
| `~/.pry/agency/` | Agency/client management |

## Module Map

| Module | Lines | Type | Purpose |
|--------|-------|------|---------|
| `api.py` | 3,849 | API | FastAPI application — 115 endpoints across 46 tag groups |
| `ultimate_scraper.py` | 343 | Scraper | 10-tier fallback scraper (direct → FlareSolverr → Playwright → Tor → cache) |
| `scraper.py` | 561 | Scraper | Core scraper engine, anti-detection, content extraction |
| `pipeline.py` | 160 | Pipeline | Hook point definitions for data processing pipelines |
| `pipelines.py` | 499 | Pipeline | Step types registry, pipeline validation and execution |
| `extraction.py` | 315 | Extraction | Chunking strategies for LLM extraction |
| `extractor.py` | 136 | Extraction | Structured data extraction from web content |
| `parser.py` | 121 | Parsing | Document parsing (PDF, DOCX, CSV, JSON, images) |
| `adaptive.py` | 175 | Detection | Anti-block adaptive scraper — rotates strategies |
| `browser_pool.py` | 95 | Browser | Playwright manager and browser pre-warming |
| `stealth_engine.py` | 176 | Browser | Stealth initialization scripts for browser contexts |
| `automator.py` | 319 | Browser | Persistent browser session with cookie management |
| `sessions.py` | 105 | Browser | Session save/restore to filesystem |
| `captcha_solver.py` | 238 | Auth | 6+ CAPTCHA solver providers with auto-fallback |
| `auth_connector.py` | 328 | Auth | Credential vault (encrypted), SSO login script generation |
| `signup_automator.py` | 177 | Auth | Identity generation, email/SMS verification automation |
| `account_manager.py` | 111 | Auth | Account pool management, session persistence, proxy scoring |
| `shadow_dom.py` | 109 | Parsing | Shadow DOM content extraction |
| `lazy_load.py` | 96 | Parsing | Lazy load and infinite scroll handling |
| `freshness.py` | 227 | Monitoring | Content hash computation for change detection |
| `monitor.py` | 301 | Monitoring | Scheduled content monitors with cron-based scheduling |
| `seo_monitor.py` | 262 | SEO | SEO analysis — title, meta, headings, keywords, readability |
| `structure_monitor.py` | 234 | Monitoring | Page structure change monitoring |
| `alerter.py` | 189 | Alerts | Multi-channel alerting (webhook, Slack, email, SMS) |
| `quality.py` | 397 | Quality | Content quality metrics — completeness, accuracy, freshness |
| `review.py` | 258 | Review | Human-in-the-loop review queue with approval/rejection |
| `reconciliation.py` | 370 | Data | Schema reconciliation across verticals (e-commerce, jobs, etc.) |
| `enrichment.py` | 206 | Data | Tech stack detection, metadata enrichment |
| `training_data.py` | 362 | Data | AI training dataset generation, PII stripping, license classification |
| `reports.py` | 266 | Reports | Client report generation |
| `costing.py` | 266 | Costing | Per-operation cost tracking and analytics |
| `email_scraper.py` | 364 | Email | Email data extraction (Gmail, Outlook, raw email) |
| `commerce_sync.py` | 191 | Commerce | WooCommerce/Shopify product sync |
| `crm_sync.py` | 359 | CRM | Salesforce/HubSpot/Zoho CRM sync |
| `destinations.py` | 361 | Export | Data export — webhooks, Slack, S3, GCS, SFTP |
| `intelligence.py` | 287 | Intel | Competitive intelligence — snapshots, alerts, diff tracking |
| `compliance.py` | 443 | Compliance | GDPR/CCPA compliance — sensitive data detection, consent |
| `gdpr.py` | 316 | GDPR | Consent management, data retention, deletion requests |
| `agency.py` | 248 | Agency | White-label agency profiles, client management, quotas |
| `jobqueue.py` | 119 | Jobs | Async job queue with status tracking |
| `network.py` | 145 | Network | Proxy rotation, Tor routing, network utilities |
| `markdown_gen.py` | 181 | Export | Markdown generation from scraped content |
| `template_engine.py` | 138 | Templates | Pre-built scraper template registry (110 templates) |
| `advanced.py` | 249 | Features | Premium features — diff tracking, vision AI, batch processing |
| `pryextras.py` | 172 | Extras | WebSocket streaming, real-time job progress |
| `mcp_server.py` | 127 | MCP | MCP tool discovery + execution (Claude/Hermes/Cursor) |
| `mconfig.py` | 129 | Config | Configuration manager — env vars, config file, API overrides |
| `settings.py` | 55 | Config | Pydantic settings with environment variable loading |
| `errors.py` | 49 | Core | Base exception hierarchy |
| `client.py` | 43 | Core | Shared httpx client singleton |
| `cache.py` | 80 | Core | LRU cache key generation with TTL |
| `ratelimit.py` | 84 | Core | Token bucket rate limiter (configurable RPM) |
| `pryfile.py` | 119 | Config | Pryfile (pry.yml) job definition parser and executor |
| `pry_sdk.py` | 130 | SDK | Async + sync Python SDK for API consumption |
| `cli.py` | 339 | CLI | Click-based CLI with autocomplete support |
| `ai_plugin.py` | 55 | AI | OpenAPI spec generation for AI agent integration |
| `api.py` | 3,849 | API | FastAPI application — 115 endpoints across 46 tag groups |

## API Endpoint Groups

| Tag | Endpoints | Purpose |
|-----|-----------|---------|
| Health | 3 | `/health`, `/live`, `/ready` |
| Stats | 1 | `/v0/stats` |
| Costing | 4 | Dashboard, usage, record, costs |
| Freshness | 3 | Dashboard, check, details |
| Scraping | 8 | Scrape, detect-block, crawl, map, PDF, lazy capture, link scrape, sitemap |
| Parsing | 3 | Parse, PDF, shadow-dom |
| Automation | 2 | Automate, screenshot |
| Vision | 2 | Analyze, describe |
| Sessions | 5 | Create, close, list, save, restore |
| Batch | 2 | Batch scrape, batch-file |
| Analysis | 6 | Compare, watch, summarize, diff, categorize, suggest |
| Extraction | 8 | Links, SEO, schema, emails, extract, extract/llm, fields, extraction run |
| Export | 1 | Export |
| Email | 3 | Scrape, gmail, outlook |
| Alerts | 2 | Send, channels |
| Jobs | 2 | Status, list |
| MCP | 2 | Tools, call |
| Config | 3 | Get, update, tor |
| Recorder | 4 | Start, step, export, clear |
| Transform | 2 | Transform, pipe |
| Execute | 1 | Run |
| Dashboard | 1 | Dashboard |
| Circuit Breaker | 2 | Status, reset |
| Pipeline | 3 | Hook, list hooks, run |
| Share | 2 | Create, view |
| Compliance | 2 | Check, docs |
| GDPR | 8 | Consent, status, revoke, deletion request/execute, retention, export, audit, policy |
| Training | 4 | Clean, dataset, list datasets, dataset detail |
| Monitoring | 5 | Create, run, list, delete, check |
| Structure | 3 | Check, history, archive |
| Intelligence | 4 | Snapshot, list, diff, report |
| Auth | 6 | Credentials store/list/delete, SSO, CAPTCHA, session health |
| Review | 6 | Submit, approve, reject, list, detail, queue |
| Quality | 3 | Check, history, score |
| Enrichment | 2 | Analyze, history |
| Reconciliation | 2 | Run, history |
| Commerce | 2 | Sync, platforms |
| CRM | 2 | Sync, platforms |
| Pipelines | 7 | Validate, run, save, list, get, delete, schema |
| Agency | 7 | Create, get, branding, client create, client list, analytics, quota |
| SEO | 3 | Analyze, track, keywords |
| Reports | 3 | Generate, list, get |
| Templates | 3 | List, get, generate |
| Integrations | 3 | Zappier, Make, webhooks |
| AI | 2 | GPT manifest, MCP config |
| System | 1 | System info |

## Security Model

- **Vault**: Encrypted credential storage at `~/.pry/vault/`
- **GDPR**: Full consent management, retention policies, deletion workflow
- **Rate limiting**: Token bucket per-IP (default 120 RPM)
- **Circuit breaker**: Per-domain backoff on failures
- **No API keys required**: Self-hosted, fully private

## External Dependencies

| Dependency | Purpose |
|------------|---------|
| FlareSolverr | Cloudflare/WAF challenge bypass (Docker sidecar) |
| Redis | Optional cache backend |
| Playwright | Full browser automation (Chromium) |
| Tor | Anonymous routing (optional) |
| OpenRouter | Vision AI models (optional) |

## Project Files

| File | Lines | Purpose |
|------|-------|---------|
| Python source files | 101 files | Core application |
| Test files | 43 files | pytest test suite |
| JSON templates | 110 files | Pre-built scraper templates |
| HTML templates | 2 files | Coverage report, browser popup |
| Stealth scripts | 6 JS files | Browser anti-detection |
| Browser extension | 5 files | Chrome extension |
| Shopify app | 3 files | Commerce integration |
| WP plugin | 1 file | WordPress integration |
| Config files | 8 files | pyproject.toml, Dockerfile, Makefile, etc. |
