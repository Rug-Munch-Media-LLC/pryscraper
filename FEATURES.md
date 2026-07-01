---
title: Pry Feature Catalog
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-06-30
---

# Pry Feature Catalog

## Scraping & Crawling

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Single URL scrape | `scraper.py` | `POST /v1/scrape` | ✅ |
| Multi-page crawl | `scraper.py` | `POST /v1/crawl` | ✅ |
| Batch scrape (parallel) | `advanced.py` | `POST /v1/batch` | ✅ |
| Batch from file + template | `advanced.py` | `POST /v1/batch-file` | ✅ |
| URL discovery (sitemap) | `scraper.py` | `POST /v1/map` | ✅ |
| Link analysis | `scraper.py` | `POST /v1/links` | ✅ |

## Anti-Detection & Bypass

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| 10-tier fallback scraper | `ultimate_scraper.py` | Internal | ✅ |
| Block detection | `adaptive.py` | `POST /v1/detect-block` | ✅ |
| Adaptive strategy rotation | `adaptive.py` | Internal | ✅ |
| Browser pool + pre-warming | `browser_pool.py` | Internal | ✅ |
| Stealth engine (6 JS scripts) | `stealth_engine.py` | Internal | ✅ |
| Stealth scripts | `stealth_scripts/` | Injected | ✅ |
| Tor proxy routing | `network.py` | `POST /v1/config/profile/tor` | ✅ |
| SOCKS5 proxy support | `network.py` | Config | ✅ |
| User-agent rotation | `scraper.py` | Internal | ✅ |

## Document Parsing

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| PDF parsing | `parser.py` | `POST /v1/parse` | ✅ |
| DOCX parsing | `parser.py` | `POST /v1/parse` | ✅ |
| Image OCR | `parser.py` | `POST /v1/parse` | ✅ |
| CSV parsing | `parser.py` | `POST /v1/parse` | ✅ |
| JSON parsing | `parser.py` | `POST /v1/parse` | ✅ |
| Shadow DOM extraction | `shadow_dom.py` | `POST /v1/shadow-dom` | ✅ |
| Lazy load / infinite scroll | `lazy_load.py` | `POST /v1/capture/lazy` | ✅ |

## Extraction & Structured Data

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| JSON schema extraction | `extractor.py` | `POST /v1/extract` | ✅ |
| LLM extraction + chunking | `extraction.py` | `POST /v1/extract/llm` | ✅ |
| Schema.org / JSON-LD | `extractor.py` | `POST /v1/schema` | ✅ |
| Email address extraction | `extractor.py` | `POST /v1/emails` | ✅ |
| Structured field extraction | `extraction.py` | `POST /v1/extract/fields` | ✅ |
| Field suggestion (AI) | `advanced.py` | `POST /v1/suggest` | ✅ |

## AI & Vision

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Vision AI (OpenRouter, 5-model fallback) | `advanced.py` | `POST /v1/vision` | ✅ |
| AI summarization (Ollama) | `advanced.py` | `POST /v1/summarize` | ✅ |
| AI categorization | `advanced.py` | `POST /v1/categorize` | ✅ |
| GPT Action manifest | `ai_plugin.py` | `GET /v1/ai/gpt-manifest` | ✅ |
| MCP server config | `ai_plugin.py` | `GET /v1/ai/mcp-config` | ✅ |
| MCP tool discovery | `mcp_server.py` | `GET /mcp/tools` | ✅ |
| MCP tool execution | `mcp_server.py` | `POST /mcp/call` | ✅ |

## Browser Automation

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Step-based automation | `automator.py` | `POST /v1/automate` | ✅ |
| Screenshot capture | `automator.py` | `POST /v1/screenshot` | ✅ |
| Persistent browser sessions | `sessions.py` | `POST /v1/session/create` | ✅ |
| Session list | `sessions.py` | `GET /v1/sessions` | ✅ |
| Session save/restore | `sessions.py` | `POST /v1/session/save` | ✅ |
| Session close | `sessions.py` | `POST /v1/session/close` | ✅ |
| Action recorder | `advanced.py` | `POST /v1/record/start` | ✅ |

## CAPTCHA Solving

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| CAPTCHA solving (6 providers) | `captcha_solver.py` | `POST /v1/auth/captcha` | ✅ |
| Auto-fallback across providers | `captcha_solver.py` | Internal | ✅ |

## Authentication

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Credential vault (encrypted) | `auth_connector.py` | `POST /v1/auth/credentials` | ✅ |
| SSO login script generation | `auth_connector.py` | `POST /v1/auth/sso` | ✅ |
| Session health check | `auth_connector.py` | `POST /v1/auth/session/health` | ✅ |
| Signup automation | `signup_automator.py` | Internal | ✅ |
| Account pool management | `account_manager.py` | Internal | ✅ |

## Monitoring & Change Detection

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Page watch / change detection | `freshness.py` | `POST /v1/watch` | ✅ |
| Diff tracking | `advanced.py` | `POST /v1/diff` | ✅ |
| Content freshness dashboard | `freshness.py` | `GET /v1/freshness/dashboard` | ✅ |
| Scheduled monitors (cron) | `monitor.py` | `POST /v1/monitor` | ✅ |
| Monitor run on-demand | `monitor.py` | `POST /v1/monitor/run` | ✅ |
| Monitor list / delete | `monitor.py` | `GET /v1/monitors` | ✅ |
| Structure monitoring | `structure_monitor.py` | `POST /v1/structure/check` | ✅ |

## Alerts & Notifications

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Multi-channel alerts | `alerter.py` | `POST /v1/alert/send` | ✅ |
| Supported channel listing | `alerter.py` | `GET /v1/alert/channels` | ✅ |
| Webhook support | `destinations.py` | Config | ✅ |
| Slack integration | `destinations.py` | Config | ✅ |

## Quality & Review

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Content quality scoring | `quality.py` | `POST /v1/quality/check` | ✅ |
| Quality history | `quality.py` | `GET /v1/quality/history` | ✅ |
| Human review queue | `review.py` | `POST /v1/review/submit` | ✅ |
| Review approve/reject | `review.py` | `POST /v1/review/{id}/approve` | ✅ |
| Review queue listing | `review.py` | `GET /v1/reviews` | ✅ |

## Data Export & Integration

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Multi-format export (JSON, CSV, RSS, TXT, SQL) | `destinations.py` | `POST /v1/export` | ✅ |
| Webhook delivery | `destinations.py` | Config | ✅ |
| S3 upload | `destinations.py` | Config | ✅ |
| GCS upload | `destinations.py` | Config | ✅ |
| SFTP upload | `destinations.py` | Config | ✅ |
| Data transformation | `advanced.py` | `POST /v1/transform` | ✅ |

## Commerce & CRM

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| WooCommerce product sync | `commerce_sync.py` | `POST /v1/commerce/sync` | ✅ |
| Shopify product sync | `commerce_sync.py` | `POST /v1/commerce/sync` | ✅ |
| Shopify app backend | `shopify-app/` | External | ✅ |
| Salesforce CRM sync | `crm_sync.py` | `POST /v1/crm/sync` | ✅ |
| HubSpot CRM sync | `crm_sync.py` | `POST /v1/crm/sync` | ✅ |
| Zoho CRM sync | `crm_sync.py` | `POST /v1/crm/sync` | ✅ |

## Pipelines

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Pipeline definition validation | `pipelines.py` | `POST /v1/pipelines/validate` | ✅ |
| Pipeline execution | `pipelines.py` | `POST /v1/pipelines/run` | ✅ |
| Pipeline CRUD | `pipelines.py` | CRUD endpoints | ✅ |
| Hook registration | `pipeline.py` | `POST /v1/pipeline/hook` | ✅ |
| Hook execution | `pipeline.py` | `POST /v1/pipeline/run` | ✅ |
| Schema pipeline | `pipelines.py` | `POST /v1/pipelines/schema` | ✅ |

## Intelligence & Competitive Analysis

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Competitor snapshot | `intelligence.py` | `POST /v1/intel/snapshot` | ✅ |
| Intel comparison (diff) | `intelligence.py` | `POST /v1/intel/compare` | ✅ |
| Intel report generation | `intelligence.py` | `GET /v1/intel/report` | ✅ |
| Tech stack detection | `enrichment.py` | `POST /v1/enrichment/analyze` | ✅ |

## Compliance & GDPR

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Compliance check (URL) | `compliance.py` | `POST /v1/compliance/check` | ✅ |
| Consent recording | `gdpr.py` | `POST /v1/gdpr/consent` | ✅ |
| Consent check / revoke | `gdpr.py` | `GET /v1/gdpr/consent/{id}` | ✅ |
| Data deletion request | `gdpr.py` | `POST /v1/gdpr/deletion/request` | ✅ |
| Deletion execution | `gdpr.py` | `POST /v1/gdpr/deletion/execute` | ✅ |
| Data retention policy | `gdpr.py` | `GET /v1/gdpr/retention` | ✅ |
| Data portability (export) | `gdpr.py` | `POST /v1/gdpr/export` | ✅ |
| Compliance audit log | `gdpr.py` | `GET /v1/gdpr/audit` | ✅ |

## Training Data

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| PII/copyright stripping | `training_data.py` | `POST /v1/training/clean` | ✅ |
| Dataset generation | `training_data.py` | `POST /v1/training/dataset` | ✅ |
| Dataset CRUD | `training_data.py` | CRUD endpoints | ✅ |
| License classification | `training_data.py` | Internal | ✅ |

## Agency / White-Label

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Agency profile creation | `agency.py` | `POST /v1/agency/create` | ✅ |
| Agency branding | `agency.py` | `PUT /v1/agency/{id}/branding` | ✅ |
| Client sub-account management | `agency.py` | `POST /v1/agency/{id}/clients` | ✅ |
| Usage analytics | `agency.py` | `GET /v1/agency/{id}/analytics` | ✅ |
| Client quota enforcement | `agency.py` | `GET /v1/client/{id}/quota` | ✅ |

## Reporting

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Report generation | `reports.py` | `POST /v1/reports/generate` | ✅ |
| Report list / get | `reports.py` | `GET /v1/reports` | ✅ |

## Templates

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| Template listing | `template_engine.py` | `GET /v1/templates` | ✅ |
| Template detail | `template_engine.py` | `GET /v1/templates/{id}` | ✅ |
| Template generation | `template_engine.py` | `POST /v1/templates/generate` | ✅ |
| Pre-built templates | 110 JSON files | `templates/` | ✅ |

## SEO

| Feature | Module | Endpoint | Status |
|---------|--------|----------|--------|
| SEO analysis | `seo_monitor.py` | `POST /v1/seo/analyze` | ✅ |
| SEO change tracking | `seo_monitor.py` | `POST /v1/seo/track` | ✅ |
| Keyword analysis | `seo_monitor.py` | `POST /v1/seo/keywords` | ✅ |

## Infrastructure

| Feature | Module | Status |
|---------|--------|--------|
| Health probes (liveness/readiness) | `api.py` | ✅ |
| Prometheus metrics | `api.py` | ✅ |
| Rate limiting (token bucket) | `ratelimit.py` | ✅ |
| LRU cache + Redis | `cache.py` | ✅ |
| Circuit breaker per-domain | `advanced.py` | ✅ |
| WebSocket streaming | `pryextras.py` | ✅ |
| Async job queue | `jobqueue.py` | ✅ |
| Docker Compose deployment | `docker-compose.yml` | ✅ |
| CI/CD (GitHub Actions) | `.github/workflows/ci.yml` | ✅ |
| Pre-commit hooks | `.pre-commit-config.yaml` | ✅ |
| Browser extension (Chrome) | `browser-extension/` | ✅ |
| WordPress plugin | `wordpress-plugin/` | ✅ |
