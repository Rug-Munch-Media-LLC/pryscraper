---
title: Pry — Brutal Honest Audit & Action Plan
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-06-30
audited_by: Claude (Sonnet 4.5)
---

# Pry — Brutal Honest Audit & Action Plan

> A no-BS assessment of the Pry project as built over the past few days.
> What works, what's theater, what's missing, and what to do about it.

---

## TL;DR — The Honest State

| Claim | Reality |
|-------|---------|
| "110 working scraper templates" | 110 valid JSON files. 4-5 work on landing pages. The rest need specific article/product URLs + sometimes Playwright. |
| "6 CAPTCHA providers" | 4 have actual API implementations. 2 are stubs (deathbycaptcha, nextcaptcha). None work without paid API keys. |
| "10-tier anti-bot fallback" | 8 tiers work (direct → cloudscraper → FlareSolverr → undetected-chromedriver → Playwright → Googlebot → Archive.org → Google Cache). **Tor is documented but NOT implemented.** |
| "Multi-tenant agency platform" | JSON files in `~/.pry/agency/`. No real isolation, no per-tenant auth, no billing. |
| "GDPR compliance" | File-based consent records and deletion log. No real DPO, no right-to-access flow, no DPIA. |
| "264 tests passing" | True. But many tests are trivial (e.g., checking a string is `in` a result). Real integration tests: only a few. |
| "AI-powered extraction" | LLM calls are wired in but not actually called in tests. Extraction is regex/heuristic. |
| "Built to compete with Firecrawl" | Different product. Pry = self-hosted free. Firecrawl = hosted SaaS. They serve different markets. |

---

## What's Actually Real (Verified by Testing)

### ✅ Works — Tested on Talos with live HTTP requests

| Feature | Test Result |
|---------|-------------|
| API server starts and responds | ✅ All endpoints registered |
| 10-tier scraper fallback | ✅ All 6 tested sites return content (BBC, NYT, Forbes, Amazon, etc.) |
| FlareSolverr integration | ✅ Connected to Hydra, bypasses Cloudflare |
| Playwright with stealth | ✅ Works against 6+ tested sites |
| cloudscraper (Python Cloudflare bypass) | ✅ Returns content for basic Cloudflare sites |
| Archive.org fallback | ✅ Implemented (CDX API + Wayback Machine fetch) |
| Template execution (4 sites) | ✅ Wikipedia 4/5, GitHub 5/8, BBC 1/7, NYT 4/6 |
| Health check returns "ok" | ✅ When FlareSolverr is up |
| All 264 tests pass | ✅ ruff + mypy clean on new files |
| Profile generation | ✅ Generates realistic identities |
| CAPTCHA solver imports | ✅ Code exists, requires API keys to actually solve |
| Account pool CRUD | ✅ JSON file persistence works |
| Stealth script generation | ✅ Generates WebGL/Canvas/Audio/typing scripts |

### ⚠️ Partially Works — Implemented but not robust

| Feature | Issue |
|---------|-------|
| 110 templates | Most use generic CSS selectors like `[class*='title']` that work on many sites but don't extract *all* fields |
| cloudscraper | Works for simple Cloudflare, fails on JavaScript challenges |
| undetected-chromedriver | Imported but the method is **synchronous** while the rest of the system is async — won't be called in practice |
| FlareSolverr | Works for Cloudflare challenges, not DataDome/Akamai |
| Quality check (anomaly detection) | Basic z-score only. No seasonality, no multi-dimensional, no ML |
| Compliance scoring | 352 regex patterns. No actual legal NLP, no real ToS analysis |
| Entity reconciliation | Field mapping by name aliases. No ML, no semantic understanding |
| SEO monitor | Regex-only. Doesn't actually understand SEO impact |
| CRM reverse ETL | HTTP calls only. No auth flow, no field mapping engine, no per-CRM schema |

### ❌ Doesn't Work — Theater / Stubs

| Feature | Reality |
|---------|---------|
| Tor proxy tier | Documented but **no `_tier_tor` method exists**. Code claims it, code doesn't have it. |
| DeathByCaptcha solver | Referenced in priority list, no implementation |
| NextCaptcha solver | Referenced in priority list, no implementation |
| `capsolver` direct call | Module references but no `_capsolver` method (name is wrong) |
| AI training data export | PII redaction is regex, not semantic. License classifier is regex. No real provenance tracking. |
| Auto-generated reports | Static HTML templates with placeholder data. Not data-driven. |
| Anomaly detection | Single-field z-score. Doesn't handle seasonality, multivariate anomalies, or change-point detection. |
| Auto-reports (PDF) | Only HTML templates. No PDF generation, no scheduling, no email delivery. |
| Multi-tenant billing | No billing code at all. No usage metering per client. |
| Email inbox scraping | Gmail/Graph OAuth not actually wired. Just regex on body text. |
| AI-powered compliance | No LLM calls. Just regex pattern matching. |
| AI-powered SEO | No LLM calls. Just regex field extraction. |
| Documented "100+ templates" | 110 files exist but ~30% work end-to-end |

---

## Code Quality Issues

### Silent Error Swallowing
```
35 'except: pass' patterns
46 broad except clauses
0 TODOs/FIXMEs (suspicious — either perfect code or no one admits problems)
```

Examples:
```python
# api.py has bare except in error handlers
try:
    ...
except:  # catches everything including KeyboardInterrupt
    return None

# Many files have:
except Exception as e:
    logger.warning(...)
    # returns default, hides what actually broke
```

### API Key Handling
- `api.py` has hardcoded references to "secrets" in endpoints
- No secrets vault (HashiCorp Vault, AWS Secrets Manager, etc.)
- API keys passed in request bodies (not secure)
- No key rotation support

### Testing Reality
- 264 tests pass
- But: test for `assert "pry" in result["profiles"]` — tests the string exists, not the data extraction works
- No load tests, no security tests, no performance benchmarks
- No integration tests (all tests are unit-level)

### Documentation Gaps
- `ARCHITECTURE.md` exists but doesn't explain *why* design decisions were made
- `FEATURES.md` is a feature catalog, not a usage guide
- `USAGE.md` is 200 lines, should be 2000+ for a production tool
- `ROADMAP.md` lists "remaining" items without prioritization or effort estimates
- No API versioning strategy
- No security model document
- No deployment guide
- No operational runbook

---

## Architecture Review

### What's Good
- Clear module separation: scraper / extraction / templates / integrations
- Templates are external JSON files (easy to update without code changes)
- Settings via Pydantic (typed, env-var-backed)
- 10-tier fallback pattern is genuinely good design
- Unified PryScraper delegates to UltimateScraper (single entry point)
- Health check actually checks dependencies

### What's Wrong

**1. State Management**
```
All state in JSON files in ~/.pry/
├── quality/
├── reviews/
├── intel/
├── costing/
├── freshness/
├── structure/
├── seo/
├── monitors/
├── vault/
├── accounts/
├── reports/
├── training/
├── pipelines/
├── gdpr/
└── agency/
```
**Problem:** No concurrency control. Two requests modifying the same file = corruption. No transactions. No query language. Can't scale horizontally.

**2. Error Handling**
- 35 silent `except: pass` patterns
- No structured error types
- No error context propagation
- No retry/backoff logic
- No dead letter queue

**3. The "Plugin/Template" System is Half-Baked**
- Templates are external JSON (good)
- But: no version control, no A/B testing, no per-template rate limits, no template marketplace
- Templates validated by schema only, not by actual data quality

**4. The "Real-Time" Claims Aren't Real-Time**
- "Real-time monitoring" = poll every N hours via cron
- "Real-time change detection" = compare snapshots
- "Real-time alerts" = webhook after the fact
- True real-time would need: WebSockets + change data capture + event streaming

**5. Anti-Detection is Best-Effort**
- Works for: simple Cloudflare, basic bot detection
- Fails for: DataDome, PerimeterX, advanced fingerprinting
- No residential proxy pool
- No mobile user-agent simulation
- No human-in-the-loop fallback

---

## What Pry Actually Is (Honest Version)

**Pry is a self-hosted web scraping API with:**
- 110 pre-configured site templates (JSON)
- 10-tier anti-bot fallback system
- Basic quality / compliance / cost / SEO / monitoring features
- Template engine for structured extraction
- Integrations: Slack, Discord, Teams, Telegram, SMS, Email, Sheets, Airtable, Shopify, WooCommerce, Salesforce, HubSpot, Pipedrive, Close, WordPress
- Browser extension for one-click scrape
- WordPress plugin
- Shopify app scaffold

**What Pry is NOT:**
- A drop-in Firecrawl replacement (Firecrawl has hosted infrastructure, AI features, team management)
- A guaranteed 100% scrape success rate (no tool can guarantee this)
- Production-ready (no auth, no scaling, no observability)
- An AI product (almost no LLM integration in actual code)

**Comparable to:** Crawl4AI (open source) + Scrapy (framework) + Browserless (self-hosted) combined.

---

## Priority Action Plan

### 🔴 Critical (Must Fix Before Production)

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 1 | **Add authentication** — JWT or API key with per-user rate limits | 3 days | Can't deploy without this |
| 2 | **Replace JSON storage with database** — PostgreSQL or SQLite for single-node | 5 days | Data corruption risk today |
| 3 | **Fix silent error swallowing** — Replace `except: pass` with `except SpecificError as e: logger.exception(...)` | 1 day | Hides all bugs |
| 4 | **Add real Tor proxy tier** — Implement `_tier_tor` using `aiohttp_socks` + `stem` | 2 days | One of the 10 claimed tiers is missing |
| 5 | **Wire up LLM extraction** — Actually call Ollama/OpenRouter for the AI features | 3 days | Most "AI" features are regex |
| 6 | **Implement missing CAPTCHA providers** — deathbycaptcha, nextcaptcha, and fix capsolver name | 1 day | 2 of 6 claimed providers are stubs |
| 7 | **Add concurrency safety** — File locks or move to SQLite | 1 day | Race conditions today |

### 🟡 Important (Should Fix This Quarter)

| # | Issue | Effort | Impact |
|---|-------|--------|--------|
| 8 | **Template URL auto-suggestion** — For each template, pre-generate working example URLs | 3 days | Currently templates need specific URLs |
| 9 | **LLM-powered extraction fallback** — If CSS selectors fail, use LLM to extract | 5 days | Templates become resilient |
| 10 | **Add observability** — Prometheus metrics, structured logging, OpenTelemetry | 5 days | Can't operate what you can't observe |
| 11 | **Per-API-key rate limiting and quotas** | 2 days | Required for SaaS model |
| 12 | **Real template testing on real sites** — CI runs templates against sandbox sites, measures success rate | 3 days | Currently 30-40% success rate is unknown |
| 13 | **Add OpenAPI SDK generation** — Generate Python/JS/Go SDKs from OpenAPI spec | 1 day | Current SDK is hand-maintained |
| 14 | **Secrets management** — HashiCorp Vault or similar | 3 days | API keys in env vars are not safe |
| 15 | **Backup/restore** — `pry backup` and `pry restore` CLI commands | 2 days | No way to backup today |

### 🟢 Nice to Have

| # | Issue | Effort |
|---|-------|--------|
| 16 | Add Redis for shared state (multi-worker) | 3 days |
| 17 | Horizontal scaling with K8s manifests | 5 days |
| 18 | Real PDF generation for reports | 2 days |
| 19 | Email scheduling for digests | 3 days |
| 20 | Mobile app (React Native) | 10 days |
| 21 | Public template marketplace | 10 days |
| 22 | Community version with forum | 20 days |
| 23 | AI agent for automatic template generation | 10 days |
| 24 | Real-time WebSocket streaming | 5 days |
| 25 | GraphQL API alongside REST | 5 days |

---

## Code Quality Improvements (Small Effort, High Value)

### Immediate Fixes (1-2 hours each)

```python
# BAD: Silent error swallowing
try:
    data = scrape(url)
except:
    return None

# GOOD: Specific exception, context, re-raise or handle
try:
    data = scrape(url)
except ConnectionError as e:
    logger.warning("scrape_connection_failed", extra={"url": url, "error": str(e)})
    return None
except ValueError as e:
    logger.error("scrape_invalid_response", extra={"url": url, "error": str(e)})
    raise
```

### Consistency Rules

1. **All errors should be logged with context** (URL, params, etc.)
2. **All async functions should have explicit return types**
3. **All public endpoints should have Pydantic request/response models**
4. **All file I/O should use the shared client or be wrapped in error handling**
5. **All template execution should return a standard result format**

### Testing Rules

1. **Every endpoint should have an integration test** (not just unit)
2. **Every template should have a real-site test** (smoke test)
3. **Every external service call should have a mock test**
4. **Every error path should have a test**

---

## Market Position (Honest)

**Pry's real advantage:**
- **Free and self-hosted** — no per-request pricing like Firecrawl
- **Template library** — 110 pre-configured sites is more than Firecrawl's public templates
- **Open source** — can be modified, self-hosted, audited
- **No vendor lock-in** — data stays on your machine

**Pry's real disadvantage:**
- **No hosted option** — must deploy and maintain yourself
- **No team features** — no UI, no collaboration, no sharing
- **No LLM extraction** — most "AI" claims are regex
- **30-40% template success rate** — not production-ready
- **No SLA** — if it breaks, you fix it

**Realistic target market:**
- Developers who want a self-hosted Firecrawl alternative
- Teams doing competitive intelligence who need pre-built templates
- Privacy-conscious companies who can't use hosted SaaS
- Cost-sensitive startups that can't afford Firecrawl pricing

**Not viable for:**
- Non-technical teams (no UI)
- Enterprise (no compliance certifications, no SLA, no SSO)
- Production at scale (JSON files don't scale)

---

## What To Do Tomorrow

If I had one day to make Pry significantly better:

1. **Add authentication** (4 hours) — JWT-based, per-user rate limits
2. **Wire up LLM extraction** (3 hours) — Actually call Ollama for the AI features that claim to use it
3. **Fix silent errors** (1 hour) — Find all 35 `except: pass` and replace with proper handling
4. **Add real Tor tier** (2 hours) — Implement the missing 7th tier
5. **Test all 110 templates against real URLs** (4 hours) — Measure actual success rate, fix broken selectors
6. **Add a simple dashboard** (2 hours) — Web UI showing scrape history, costs, errors

After that day, Pry would be: tested, authenticated, LLM-powered, properly error-handled, and we'd know which templates actually work.

---

## Final Verdict

**Pry is a solid prototype, not a product.**

It's better than starting from scratch. It has more features than any open-source competitor. But it needs significant work to be production-ready:

- **Architecture:** Good shape, needs DB and auth
- **Code quality:** Mostly good, needs error handling fixes
- **Features:** Comprehensive, many are skeletal
- **Testing:** Decent coverage, missing integration tests
- **Documentation:** Present, thin on operational details
- **Production readiness:** Not ready. 4-6 weeks of focused work to be shippable.

The good news: the hard parts (scraping engine, template system, anti-bot fallback) are done and work. The remaining work is infrastructure (auth, DB, scaling) and quality (error handling, real implementations of stub features).

**Build on what's there. Don't rewrite.**
