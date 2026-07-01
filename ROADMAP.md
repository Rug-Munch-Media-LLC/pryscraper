---
title: Pry Roadmap & Status
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-06-30
---

# Pry Roadmap

## Current Status: v3.0.0 — Active Development

Pry is a mature, feature-complete self-hosted web scraping platform. This roadmap tracks remaining gaps and planned improvements.

## What's Built (✅ Complete)

### Core Scraping Engine
- ✅ 10-tier fallback scraper (direct → FlareSolverr → Playwright → Tor → cache)
- ✅ Block detection with adaptive strategy rotation
- ✅ Document parsing (PDF, DOCX, OCR, CSV, JSON)
- ✅ Shadow DOM extraction
- ✅ Lazy load / infinite scroll handling

### Anti-Detection
- ✅ Cloudflare bypass via FlareSolverr
- ✅ undetected-chromedriver integration
- ✅ Stealth engine (6 anti-detection JS scripts)
- ✅ User-agent rotation
- ✅ Tor proxy routing
- ✅ SOCKS5 proxy support
- ✅ Browser pool with pre-warming

### API (115 endpoints)
- ✅ REST API with 46 endpoint groups
- ✅ Health probes (liveness, readiness)
- ✅ Prometheus metrics
- ✅ Rate limiting (token bucket)
- ✅ Circuit breaker (per-domain)
- ✅ WebSocket streaming
- ✅ Async job queue
- ✅ MCP server (Claude/Hermes/Cursor compatible)

### Auth & Automation
- ✅ CAPTCHA solver (6 providers, auto-fallback)
- ✅ Credential vault (encrypted)
- ✅ SSO login script generation
- ✅ Session management (create, save, restore, close)
- ✅ Browser action recorder
- ✅ Signup automation
- ✅ Account pool management

### Extraction & Analysis
- ✅ JSON schema extraction
- ✅ LLM extraction with chunking strategies
- ✅ Schema.org/JSON-LD extraction
- ✅ Email extraction (Gmail, Outlook, raw)
- ✅ AI summarization (Ollama)
- ✅ AI categorization
- ✅ Vision AI (OpenRouter, 5-model fallback)
- ✅ SEO analysis (title, meta, headings, keywords, readability)
- ✅ Tech stack detection
- ✅ Field suggestion (AI)

### Monitoring & Alerts
- ✅ Page change detection (content fingerprinting)
- ✅ Diff tracking between versions
- ✅ Scheduled monitors (cron-based)
- ✅ Content freshness dashboard
- ✅ Structure change monitoring
- ✅ Multi-channel alerts (webhook, Slack, email, SMS)

### Data Pipeline
- ✅ Pipeline definition, validation, and execution
- ✅ Hook registration and execution
- ✅ Data transformation (JSON, CSV, RSS, TXT, SQL)
- ✅ Multi-format export
- ✅ Webhook delivery, S3, GCS, SFTP

### Quality & Review
- ✅ Content quality scoring (completeness, accuracy, freshness)
- ✅ Human review queue (submit, approve, reject)
- ✅ Quality history tracking

### Commerce & CRM
- ✅ WooCommerce product sync
- ✅ Shopify product sync (with Shopify app backend)
- ✅ Salesforce CRM sync
- ✅ HubSpot CRM sync
- ✅ Zoho CRM sync

### Compliance
- ✅ GDPR consent management
- ✅ Data retention policies
- ✅ Data deletion (right to be forgotten)
- ✅ Data portability (export)
- ✅ Compliance audit log
- ✅ Sensitive data detection
- ✅ PII/copyright stripping for training data

### Agency
- ✅ White-label agency profiles
- ✅ Client sub-account management
- ✅ Usage analytics
- ✅ Quota enforcement

### Training Data
- ✅ Dataset generation from scraped content
- ✅ PII and copyright stripping
- ✅ License classification
- ✅ Dataset CRUD

### Templates (110+)
- ✅ Pre-built scraper templates for major sites
- ✅ Template engine with parameterization
- ✅ Template CRUD

### Intelligence
- ✅ Competitive intelligence snapshots
- ✅ Competitor comparison/diff
- ✅ Intel report generation

### Integrations
- ✅ Webhook support
- ✅ Zapier integration
- ✅ Make (formerly Integromat) integration
- ✅ Browser extension (Chrome)
- ✅ WordPress plugin
- ✅ Shopify app
- ✅ GPT Action manifest
- ✅ MCP server config
- ✅ CLI with autocomplete (bash, zsh, fish)

### Infrastructure
- ✅ Docker Compose deployment
- ✅ Dockerfile
- ✅ GitHub Actions CI/CD
- ✅ Pre-commit hooks (ruff, mypy, bandit, gitleaks)
- ✅ Makefile with standardized targets
- ✅ pyproject.toml with ruff/mypy/pytest config

## What's Remaining (🔜 Planned)

### High Priority
- [ ] Comprehensive test coverage > 80% (current: ~266 tests, ~40% coverage)
- [ ] End-to-end integration tests with FlareSolverr + Playwright
- [ ] OpenAPI specification cleanup and versioning
- [ ] Type annotations across all modules (mypy strict)

### Medium Priority
- [ ] Redis-based distributed rate limiting
- [ ] PostgreSQL-backed job queue (beyond filesystem)
- [ ] Web dashboard (beyond current `/dashboard` health view)
- [ ] API key authentication for multi-user deployments
- [ ] OpenTelemetry tracing instrumentation
- [ ] Prometheus metrics for all modules (currently only in `api.py`)

### Low Priority
- [ ] GraphQL API alternative
- [ ] Webhook retry with exponential backoff
- [ ] Template marketplace / sharing
- [ ] i18n for multi-language content extraction
- [ ] Mobile app (React Native) companion
- [ ] Desktop app (Electron) companion

## Audit Metrics (2026-06-30)

| Metric | Value |
|--------|-------|
| Version | 3.0.0 |
| Python source files | 101 |
| Total lines of Python | 18,567 |
| Test files | 43 |
| Total test functions | 266 |
| API endpoints | 115 |
| Endpoint groups (tags) | 46 |
| JSON scraper templates | 110 |
| HTML templates | 2 |
| Stealth JS scripts | 6 |
| Browser extension files | 5 |
| Shopify app files | 3 |
| WordPress plugin files | 1 |
| Config/support files | 8 |
| Total functions (all modules) | 455 |
| Total classes | 48 |
