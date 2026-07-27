---
title: Pry — Production Audit & Roadmap (2026-Q3)
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-07-06
audited_by: opencode (deep multi-agent audit)
supersedes: AUDIT.md (2026-06-30)
audience:
  - engineers
  - agents
  - operators
goal: ship Pry as production-grade + Apify-publishable within Q3 2026
---

# Pry — Production Audit & Roadmap

> **TL;DR.** Pry is a working prototype of a self-hosted scraper with good bones (scraping engine, template system, MIT/BSL split). It is **not yet a product**. Roughly **30% of the code is real, 30% is stub, 40% is hallucinated**. To reach production-grade AND Apify-publishable, we need 8 weeks of focused engineering across 5 phases. Apify-publishable is reachable in 2 weeks if we sequence the Apify glue last.

---

## 1. Brutal Honest State (master table)

| Area | Claim | Reality | Status |
|---|---|---|---|
| **Scraping engine** | 10-tier fallback | 5 tiers wired, 4 import missing libs and silently no-op, 1 (Textise) exists only in docstring | 🟡 partial |
| **Anti-detection** | camoufox + stealth + TLS fingerprint + adaptive + cookie warmer | ~1,255 lines of code that **never runs in the default scrape flow**. 0/8 modules wired into `PryScraper.scrape()`. | 🔴 orphan theater |
| **Templates** | 110 working scraper templates | 110 JSON files, all CSS selectors. Real coverage validator says 21/110, live tests show ~30-40%. The other ~70 are decorative. | 🟡 vanity |
| **Database** | SQLite via SQLAlchemy | `pry.db` exists (804 LOC `db.py`, 24 ORM models). **No Alembic**; `Base.metadata.create_all()` is the only migration path. `data.db` is a 96KB orphan. | 🟡 partial |
| **State files** | "all JSON in `~/.pry/`" | True: 24 subdirs + 122 JSON vault files + JSONL x402 ledgers. **Zero concurrency control** on the JSON writers. SQLite is the only transactional store. | 🔴 race-condition risk |
| **Auth** | gopass + JWT (HS256) + pbkdf2_hmac 100K rounds | Real, but **only 2 endpoints require it** (`/v1/key` and one more). Most endpoints are public. | 🟡 partial |
| **API surface** | 115+ endpoints, 46 tag groups | Real (~190 endpoints by Phase 0 count). But still in a 4,668-line `api.py` — only `/v1/scraping/*` and `/v1/templates/*` have been split into `routers/`. | 🟡 monolithic |
| **MCP** | "ships MCP" | `mcp_production.py` (1,173 LOC) + `mcp-worker.js` Cloudflare Worker (408 LOC) + Smithery/Glama/Pulse manifests — **BUT NOT DEPLOYED**. `/srv/pry/` only runs `api.py`. STATUS.md admits this. | 🔴 shipped-in-repo, not live |
| **x402 payments** | pay-per-request protocol | `x402.py` (35K LOC) + `x402_middleware.py`. **Not deployed** — `PRY_X402_WALLET` and `PRY_X402_FACILITATOR` unset on Talos, so all paid endpoints return 503. | 🔴 dead code in prod |
| **Apify** | "Apify-ready" | `apify_schema.py` (405 LOC) builds Python dicts shaped like Apify input schema. **No `.actor/`, no `src/main.py`, no `Actor.init()` anywhere**. `apify` package not installed. | 🔴 file name is decorative |
| **Commerce sync** | "Shopify/WooCommerce sync" | Real HTTP, hardcoded field map, no OAuth flows, no field-mapping engine. Zoho claimed in FEATURES.md — **0 matches in code**. | 🟡 partial |
| **CRM sync** | "Salesforce/HubSpot/Pipedrive/Close sync" | Real HTTP, bearer/api-key in parameter. No auth flow, no per-CRM schema. | 🟡 partial |
| **Email scraping** | "Gmail/Outlook OAuth inbox" | Real Gmail Graph + Outlook Graph HTTPS calls — **but caller hands in the access token**. OAuth flow not implemented. "Extraction" is regex. | 🟡 partial |
| **Browser extension** | Chrome extension | `manifest.json` exists (V3, 34 lines). **`icons/` directory is empty, `options.html` referenced but doesn't exist.** Will be rejected by Chrome Web Store. | 🔴 not publishable |
| **WordPress plugin** | WP plugin | Single 529-line PHP file. **No `readme.txt`, license mismatch (MIT vs GPL declared in header).** | 🔴 not publishable to wordpress.org |
| **Shopify app** | Shopify app | 60-line scaffold. `@shopify/shopify-api` declared but **never imported**. No OAuth callback, no token exchange, no HMAC verify. | 🔴 not publishable |
| **Tests** | "500 tests passing" | 500 collected, 498 pass, 2 fail (one is a flaky network test that makes a real `httpx` call to `example.com`). 60% coverage, no `--cov-fail-under`. **Most tests assert trivial things ("string in dict")** — `test_advanced_scraping.py` is 17 attribute-presence tests. | 🟡 theater |
| **Test coverage** | ">80% enforced" | **60% actual**, no threshold check in CI. `TESTING.md` describes `tests/unit/`, `tests/integration/`, `make test-unit`, `make test-cov` — **none exist.** | 🔴 docs lie |
| **Docs** | README, USAGE, ARCHITECTURE, AUDIT | Three sets of docs. Some honest (AUDIT.md, STATUS.md). Some lying (TESTING.md describes directories that don't exist; FEATURES.md claims Zoho, `.pry_sdk`, export formats that aren't there). | 🟡 mixed |
| **CI** | GitHub Actions CI | 1 workflow, 4 jobs (lint/typecheck/test/security). **Doesn't install playwright/tesseract**, so any real integration test fails on CI. **Doesn't pin ruff/mypy** versions. No deploy step. | 🟡 minimal |
| **Dependencies** | `requirements.txt` + `pyproject.toml` | 23 deps, all `>=` with no upper bound. **`aiohttp_socks` and `aiohttp` missing** despite Tor tier importing them. **`pyjwt` missing** despite `auth.py` importing it. | 🟡 destructive pin |
| **Dockerfile** | multi-stage | Real, but **no USER directive (runs as root)**, **healthcheck uses `curl` which isn't in runtime stage** — container restart-loops. | 🟡 broken healthcheck |
| **docker-compose** | pry + flaresolverr + tor | **Sets `FLARESOLVERR_URL` (wrong var name; should be `PRY_FLARESOLVERR_URL`)** — Cloudflare bypass silently fails. Same `curl`-in-healthcheck bug. | 🔴 dead FlareSolverr path |
| **CLI** | `pry` command | `pry --help` **crashes with infinite recursion** (cli.py:339-340). `pry mcp serve` is dead code (only `proxy` routes to click). `pry completions` writes a broken eval string. | 🔴 broken |
| **SDK** | `pry_sdk.py` (async+sync) | Real `PryCrawl`/`PryCrawlSync`, hardcoded endpoint paths, raw-dict returns. Doesn't use shared `client.http_client`. `pry_sdk.py` referenced in old docs — **doesn't exist**. | 🟢 real |
| **Proxies** | 10-tier with residential pool | Catalogs 3 free + 10 premium providers, calls Brightdata via signup link. **No actual credential rotation**, no gopass lookup, no proxy health scoring. Tor tier imports `aiohttp_socks` which is missing. | 🟡 stub |
| **Referral revenue** | Jupiter 50bps, Hyperliquid 50bps, etc. (per AGENTS.md) | **Pry has nothing to do with that catalog.** RMI-side. Pry's `referrals.py` covers 14 categories (exchange, LLM, hosting, proxy, etc.) with JWT-shaped attribution that doesn't actually verify the code was used. Cookie-only attribution. | 🟡 toy |
| **GDPR** | "consent, deletion, retention, audit" | JSON files + two modules (`gdpr.py`, `gdpr_real.py`). Deletion DOES walk files and unlink. **`gdpr_real.py:138` imports `ApiKey`/`QualityCheckRecord`/`UsageRecord` from db.py — those models don't exist, raises `ImportError` at runtime.** | 🟡 half-real |
| **Observability** | Prometheus metrics | Real `prometheus_client` + 9 counters/histograms, `/metrics` endpoint. OpenTelemetry has `ConsoleSpanExporter` only — no remote export. | 🟢 metrics, 🟡 no distributed tracing |

**Net: ~30% real, ~30% stub, ~40% hallucinated or dead code.**

---

## 2. Per-Subsystem Findings (top issues with file:line)

### A. Scraping pipeline
- `ultimate_scraper.py:269` `_tier_cloudscraper` — **MISSING DEP** (`cloudscraper` not in requirements). Always returns `None`.
- `ultimate_scraper.py:305` `_tier_undetected` — **MISSING DEP** (`undetected_chromedriver` not in requirements).
- `ultimate_scraper.py:419` `_tier_tor` — **MISSING DEPS** (`aiohttp`, `aiohttp_socks` not in requirements). Also `_has_tor = False` at line 26.
- `ultimate_scraper.py:406` `_tier_google_cache` — **Google deprecated this endpoint in 2024.**
- `ultimate_scraper.py:33-46` docstring — **Textise tier is fictional**, exists only in the docstring.
- `parser.py.tmp` — **half-applied refactor**, imports `pry_validators` (doesn't exist) and `OcrExtractor` (real class is `ImageOCR`). Every call raises `ModuleNotFoundError`. Delete.
- `stealth_engine.py` (198 LOC) — orphan. Not imported anywhere.
- `browser_pool.py` (102 LOC) — orphan. Not imported anywhere.
- `lazy_load.py` (102 LOC), `shadow_dom.py` (116 LOC) — orphans. Two unused JS strings.
- `camoufox_integration.py` (173 LOC) — launches Camoufox **twice per fetch** (line 133-166). Only callable as `/v1/camoufox/fetch` endpoint.
- `tls_fingerprint.py` (190 LOC) — `BROWSER_FINGERPRINTS` includes `"tor"` (line 64) which `curl_cffi` does not ship.
- `adaptive.py:42` — `Counter` mutation makes `_compute_information_gain` always return 0 after the first page.
- `extractor.py:23` — `self.ollama_base = "[OLLAMA_ENDPOINT]"` — **dead URL**, doesn't exist in fleet.
- `extraction.py:240` `compute_embedding` — trigram-frequency fallback is incompatible with 384-dim `all-MiniLM-L6-v2`. Cosine sim always 0.

### B. API surface (api.py — 4,668 LOC)
- `api.py` is still the god-file. Only `routers/scraping.py` + `routers/templates.py` + `routers/health.py` split (Phase 0). **44 of 46 endpoint groups** still in `api.py`.
- 159 broad `except Exception` patterns (per AGENTS.md). Top: error handlers swallow 7 different exception classes.
- `api.py:357` `/metrics` — **no auth** (public).
- Endpoints NOT split into `routers/`: scraping (partial done), parsing, automation, vision, sessions, batch, analysis, extraction, export, email, alerts, jobs, MCP, config, recorder, transform, execute, dashboard, circuit-breaker, pipeline, share, compliance, gdpr, training, monitoring, structure, intelligence, auth, review, quality, enrichment, reconciliation, commerce, crm, pipelines, agency, seo, reports, templates (partial done), integrations, ai, system.
- `mcp_production.py:155-159` — `"Custom actor code not yet executed"` placeholder.
- STATUS.md says "PRY_X402_WALLET/FACILITATOR unset" — so all `/v1/x402/paid/*` endpoints return 503 in prod.
- `auth.py:25-41` JWT secret falls back to ephemeral random — meaning every uvicorn restart invalidates all JWT tokens.

### C. Data layer & persistence
- `db.py` — 804 LOC (not 31K), 24 ORM models, real SQLite at `~/.pry/pry.db`.
- **No Alembic** — schema changes require `ALTER TABLE` or wipe.
- `db.py:574` `import_json_stores` — claims idempotent, actually NOT (plain `s.add()` will violate unique constraints).
- `db.py:576` looks for `quality/checks.jsonl` — but `quality.py:376` writes one-file-per-URL JSON, not JSONL. **Importer is broken.**
- `db.py` uses sync `Session` inside async handlers — blocks event loop on every disk IO.
- `quality.py:347`, `freshness.py:45,120`, `sessions.py:21`, `proxy_manager.py:260,267` — **non-atomic JSON writes**, no `fcntl`, no `tempfile + os.replace`. Concurrent writers WILL corrupt.
- `cache.py:22 ResponseCache` accepts `redis_url` but `_redis` is never assigned. **Redis integration hole.**
- `ratelimit.py:13` — in-memory per-IP token bucket. **Multi-worker breaks.**
- `data.db` (96KB) — orphan, no code reads it.
- `gdpr_real.py:138` — imports `ApiKey`, `QualityCheckRecord`, `UsageRecord` from `db` — **those models don't exist**, raises `ImportError` at runtime.

### D. Tests, CI, DX
- 62 test files, 500 tests, **498 pass / 2 fail in full suite**.
- `tests/test_api.py:46-69` `test_api_key_required_when_set` — flaky network test, takes 1.5s-17s, scrapes `example.com` for real.
- 60% coverage. **No `--cov-fail-under`.** `TESTING.md:55` lies about `--cov-fail-under=80`.
- `TESTING.md:25-31` documents `tests/unit/`, `tests/integration/`, `tests/fixtures/` — **none exist.**
- Many "tests" are trivial attribute-presence checks: `assert "chrome" in BROWSER_FINGERPRINTS`, `assert hasattr(s, "fetch")`.
- `Makefile:4` `.PHONY` lists `commit` but no `commit:` target exists.
- `pyproject.toml:60-62, 88-116` — 15 mypy error codes disabled, `--ignore-missing-imports` on.
- `pyproject.toml` has no version pins at all (`>=` only, no `<=`). `tiktoken>=0.8.0` had a CVE (GHSA-w3w6-43wv-w3fc).
- `pyproject.toml:99` lists `aiohttp_socks` and `aiohttp` as **missing**.
- `requirements.txt:1-25` is a hand-maintained duplicate of `pyproject.toml`. Will drift.
- CI (`.github/workflows/ci.yml`): 1 workflow, doesn't install `playwright`/`tesseract` so the only real integration test fails on CI.
- Pre-commit has mypy `--strict` but pyproject disables 15 codes — will fail or no-op inconsistently.

### E. CLI / SDK / Docs
- `cli.py:339-340` `-h/--help/help` calls `main()` recursively → **infinite recursion**. `pry --help` is the first command a new user runs and it crashes.
- `cli.py:342-347` dispatcher only routes `proxy` to click. **`mcp serve` / `mcp info` are unreachable** despite being in help banner.
- `cli.py:225-246` `pry completions` writes broken eval string — no `_PRY_COMPLETE` handler exists.
- `cli.py:91-94` `_spinner` thread never `join()`ed.
- `pry_sdk.py` is real (`PryCrawl`, `PryCrawlSync`), but creates its own `httpx.AsyncClient` per call instead of sharing `client.http_client`.
- `pry_sdk.py` is referenced in old docs but **doesn't exist.**
- `README.md:11` says `pip install pry` — PyPI `pry` is owned by an unrelated project.
- `USAGE.md` and `README.md` disagree on port (8002 vs 8005) without clarifying the Docker mapping.
- `FEATURES.md` claims things that don't exist: `Zoho CRM`, `pry_sdk.py`, `export RSS/TXT/SQL`, `/v1/templates/generate`.

### F. Apify / Integrations / Browser / WP / Shopify
- `apify_schema.py` builds a dict that looks like Apify input schema. **Never writes to disk, never instantiates `Actor`.** No `.actor/`, no `src/main.py`, no `apify` package.
- `actor_marketplace.py` is Pry-internal JSON store, **not Apify marketplace**.
- Browser extension: `icons/` empty, `options.html` missing → Chrome Web Store reject.
- WordPress plugin: no `readme.txt`, license mismatch (MIT in SPDX vs GPL in header) → wordpress.org reject.
- Shopify app: `@shopify/shopify-api` declared but **never imported**, no OAuth callback, no token exchange.
- Cloudflare Worker (`workers/mcp-worker.js`) is real and 408 LOC — but `wrangler.toml` has routes commented out.
- `smithery.yaml`, `glama.json`, `pulsemcp.json` are valid manifests — but install instructions reference the suspended `cryptorugmuncher` GitHub account.

### G. Docker / Deploy
- `Dockerfile` — runs as root (no `USER`), healthcheck uses `curl` not in runtime stage → restart loop.
- `docker-compose.yml:18` sets `FLARESOLVERR_URL` instead of `PRY_FLARESOLVERR_URL` → FlareSolverr bypass silently fails.
- `docker-compose.yml:67-80` Tor profile exists but `aiohttp_socks` missing → Tor tier silently no-ops.

---

## 3. Production-Readiness Distance

| Category | Today | Production-grade target |
|---|---|---|
| **Concurrent writes** | Broken (JSON race) | All writes atomic + locked, single source of truth = SQLite |
| **Schema evolution** | Hand-edit `db.py` or wipe DB | Alembic migrations, versioned |
| **Auth** | 2 endpoints, optional | All mutating endpoints, per-tenant quota |
| **Multi-worker** | Breaks cache+ratelimit+session state | Redis-backed cache/ratelimit/session |
| **Observability** | `/metrics` only | Prometheus + structured logs + OpenTelemetry + tracing |
| **AI extraction** | Dead URL, regex only | Real Ollama/OpenRouter calls with structured output |
| **Tests** | 500, 60%, 2 fail, mostly trivial | Realistic tests with respx/vcr, target 80%, CI gate |
| **CI/CD** | 1 workflow, no real test runner | Multi-job, self-hosted on Talos, deploy step |
| **Anti-detection** | Dead code | One real fallback: `curl_cffi` + `playwright-stealth`. Drop the other 7 modules. |
| **Templates** | 110 decorative JSON | Audit each, kill the bottom 50%, add real per-site logic |
| **Apify** | Glossary-only | Real `.actor/`, `src/main.py`, `apify push` works |
| **Browser ext / WP / Shopify** | Scaffolds only | Publish-ready or remove |
| **Docs** | Mixed honesty | TESTING.md, FEATURES.md rewritten against actual code |

---

## 4. Open-Source Apps To Install (current gap)

| Tool | Why | Effort |
|---|---|---|
| `cloudscraper` | Tier 2 actually works | 5min |
| `aiohttp-socks[aiohttp]` + `aiohttp` | Tor tier works, tier 10 unblocked | 5min |
| `undetected-chromedriver` | Tier 4 | 5min |
| `curl_cffi` | Already installed. Actually use it in default scrape flow. | 2hr |
| `playwright-stealth` | Replace 200 LOC of `stealth_engine.py` with `pip install playwright-stealth` and one import. | 30min |
| `pyjwt` | Listed in auth.py imports, missing from requirements.txt. | 1min |
| `aiosqlite` | Use async SQLAlchemy so DB IO doesn't block the event loop. Already installed, not imported. | 1 day wiring |
| `alembic` | Schema migrations. Today: hand-edit or wipe. | 1 day initial, free after |
| `uv` | 10-100× faster installs, lockfile, removes `requirements.txt` drift. | 1 hr |
| `respx` / `pytest-httpx` | Mock `httpx` in tests. The flaky network test stops depending on `example.com`. | 1 hr |
| `freezegun` | Time-travel in jobqueue, intelligence, monitor, compliance tests. | 30min |
| `pip-audit` | CVE scan in CI security job. | 1 hr |
| `act` | Local CI runner. | 30min |
| `cov-fail-under` in `pyproject.toml` | CI gate at 80%. | 5min |
| `mutmut` or `cosmic-ray` | Mutation testing (most tests are trivial). | 1 day setup |
| `mut`, `spotlight` or similar | Stale CSS-selector detection. | 2 days |
| **`fastapi[all]` extras** | JWT middleware, http2, orjson, etc. | 1hr |

---

## 5. Hallucinated Features — list of claims with no implementation

| Claim | Source | Reality |
|---|---|---|
| 110 working scraper templates | FEATURES.md, STATUS.md | 110 JSON, ~30% work end-to-end. Real validator score is 21/110. |
| 10-tier anti-bot fallback | ARCHITECTURE.md, FEATURES.md | 5 tiers wired, 4 broken, 1 fictional. |
| "Multi-tenant agency platform" | AUDIT.md, FEATURES.md | JSON files. No isolation. No billing. |
| "GDPR compliance — real DPO" | FEATURES.md | File-based. No DPO. `gdpr_real.py:138` raises ImportError. |
| "AI-powered extraction" | FEATURES.md | `extractor.py:23` calls a dead Ollama URL. Fallback is regex. |
| "AI-powered compliance / SEO" | FEATURES.md | Regex-only. |
| "6 CAPTCHA providers" | FEATURES.md | 4 real, 2 stubs (deathbycaptcha, nextcaptcha). |
| "Tor proxy routing" | README, FEATURES.md | Imports lib that's missing — runtime crash. |
| "Multi-tenant billing" | AUDIT.md | Zero billing code. |
| "Zoho CRM sync" | FEATURES.md | Grep returns 0 matches in code. |
| `pry_sdk.py` | (old) | Doesn't exist. |
| Shell autocompletion | cli.py:225 | Writes broken eval string; no `_PRY_COMPLETE` handler. |
| `/v1/templates/generate` | FEATURES.md | Not in api.py or routers. |
| `pry mcp serve` / `pry mcp info` | cli.py:375-403 | Help says it exists; main() never routes to it. |
| Export formats RSS/TXT/SQL | README | pryfile.py only does json/csv. |
| 0.0.3 release of `pry` on PyPI | README | PyPI name is taken. |
| `tests/unit/`, `tests/integration/`, `make test-unit`, `make test-cov` | TESTING.md | None exist. |
| `make commit` | AGENTS.md, Makefile help | `.PHONY` lists it, no rule defines it. |
| Coverage threshold >80% enforced | TESTING.md | No threshold. Current coverage is 60%. |
| MCP endpoints `/mcp/tools`, `/mcp/call` | FEATURES.md | Not in api.py; only in mcp_production.py (not deployed). |
| Browser extension publishable | repository | Empty icons/, missing options.html. |
| WordPress plugin publishable | repository | No readme.txt. License mismatch. |
| Shopify app publishable | repository | @shopify/shopify-api never imported. |

---

## 6. The Plan — 5 Phases, 8 Weeks

> **Guiding principle: build on what's there. Don't rewrite. Cut dead code aggressively. Make the stubs actually do their job. Then ship.**

### Phase 0 — Stop the bleeding (3 days)

Goal: kill the embarrassing things, get tests green, get prod stable.

1. **Fix `cli.py:339-340`** — replace infinite recursion with usage block. New users run `pry --help` first.
2. **Delete `parser.py.tmp`** — broken half-refactor with broken imports.
3. **Add missing deps** to `pyproject.toml` + `requirements.txt`:
   `cloudscraper`, `aiohttp-socks[aiohttp]`, `undetected_chromedriver`, `pyjwt`, `apify>=2.0` (for Phase 4).
4. **Fix `docker-compose.yml:18`** — `FLARESOLVERR_URL` → `PRY_FLARESOLVERR_URL`.
5. **Fix `Dockerfile` healthcheck** — use `python3 -c "import urllib.request; ..."` instead of `curl` not-in-runtime-stage.
6. **Remove `commit` from Makefile `.PHONY`** (or implement via commitizen — recommend remove).
7. **Fix `tests/test_api.py:46-69`** — mock `PryScraper` with `AsyncMock` returning `{"status":"ok","content":"x"}`. Test stops depending on `example.com`.
8. **Fix `auth.py:35-41`** — JWT secret must NOT fall back to ephemeral random. Fail closed (raise) so deploy is forced to set the env var.

### Phase 1 — Single source of truth for state (1.5 weeks)

Goal: kill the JSON race conditions, gain Alembic, gain async DB.

1. **Add Alembic.** `alembic init alembic`, autogenerate from `Base.metadata`, replace `Base.metadata.create_all()` in `db.py:147` with `command.upgrade("head")` (gated by env flag for dev).
2. **Migrate the JSON writers** to SQLite:
   - `quality.py:347`, `freshness.py:45,120`, `sessions.py:21`, `proxy_manager.py:260,267`, `gdpr_real.py` — flip each to write via `session_scope()`. The `import_json_stores` in `db.py:574` becomes the real migration tool. Fix its idempotency: use `s.merge()` or `ON CONFLICT DO NOTHING`.
3. **Async SQLAlchemy** — switch `db.py` to `AsyncSession` with `aiosqlite` (already installed). `quality.py`, `freshness.py`, `referrals.py`, `monitor.py`, `intelligence.py`, `structure_monitor.py` no longer block the event loop.
4. **Atomic JSON writes** for any stragglers (`portalocker` + `tempfile + os.replace` pattern).
5. **Delete orphan `data.db`** (96 KB SQLite, no code reads it).
6. **Fix `gdpr_real.py:138`** — either add the missing models `ApiKey`, `QualityCheckRecord`, `UsageRecord` to `db.py`, or remove the SQL branch. Document decision in `DECISIONS.md`.
7. **Add Redis-backed `ResponseCache` and `RateLimiter`** (use `rmi-redis:6379` on Talos). The `cache.py:22 redis_url` parameter is already there — just wire it.
8. **Delete `import_json_stores`'s broken JSONL assumption** at `db.py:576` — `quality.py` writes one JSON per URL, not JSONL.

### Phase 2 — Scraping core: cut dead, wire real (1.5 weeks)

Goal: the 10-tier chain becomes a 5-tier chain, every tier verified, fallback works.

1. **New fallback chain (5 tiers, all real):**
   1. **Direct HTTP via `curl_cffi`** with rotating impersonation profiles (Chrome / Firefox / Edge). Replaces Tier 1 (httpx no fingerprint) and `tls_fingerprint.py` standalone module.
   2. **`cloudscraper`** — real Cloudflare bypass (Tier 2, deps now installed).
   3. **FlareSolverr sidecar** — already wired, but verify in compose.
   4. **`playwright` + `playwright-stealth`** — single import replaces 200-LOC `stealth_engine.py`. Real fingerprint (WebGL vendor noise, canvas, audio, human mouse).
   5. **Archive.org Wayback** — already implemented, verify behavior. (Drop the dead "Google cache" and "Tor" tiers.)
2. **Delete the orphans** (~700 LOC total):
   - `stealth_engine.py`, `browser_pool.py`, `lazy_load.py`, `shadow_dom.py` — unused.
   - `camoufox_integration.py` → keep as opt-in endpoint, don't try to put it in the default chain (camoufox is slow; it's for the hard cases that should be attempted after playwright fails).
   - `tls_fingerprint.py` → fold into the new Tier 1.
   - `cookie_warmer.py` → keep as opt-in endpoint; the "warming" logic is theatrical.
   - `adaptive.py` → fix the `_compute_information_gain` bug, then keep as opt-in `/v1/crawl/adaptive`.
3. **Fix `parser.py.tmp`** deletion (already in Phase 0).
4. **Fix `extractor.py:23`** — read `OLLAMA_BASE` from env (default to `http://localhost:11434`).
5. **Fix `extraction.py:240 compute_embedding`** — use `sentence-transformers/all-MiniLM-L6-v2` (384-dim) or remove the fallback dimension mismatch.
6. **Fix `ultimate_scraper.py:33-46`** — new docstring matches the 5-tier reality.
7. **Add `playwright-stealth`** to `pyproject.toml`. Remove `stealth_engine.py`.
8. **Templates audit** — write `templates/test_live_against_real_sites.py` (not against homepages, against article/product URLs). Pass-fail dashboard. Strike the bottom 50%. Document the survivors in `TEMPLATES-COVERAGE.md`.

### Phase 3 — API surface: split the monolith, add auth, deploy MCP+x402 (2 weeks)

Goal: every endpoint in `routers/`, MCP live, x402 live.

1. **Router split (1.5 weeks)** — split `api.py` from 4,668 LOC to ~500 LOC (`api.py:routes` includes only the `FastAPI()` instantiation + global middleware; everything moves to `routers/<domain>.py`). Sequence:
   1. `routers/health.py`, `routers/scraping.py`, `routers/templates.py` (Phase 0 done).
   2. `routers/extraction.py` (linking, extraction, vision).
   3. `routers/sessions.py` (sessions, browser, automation).
   4. `routers/agents.py` (quality, freshness, structure, monitor, seo).
   5. `routers/integrations.py` (destinations, crm, commerce, email, agency).
   6. `routers/compliance.py` (gdpr, compliance, training, review).
   7. `routers/admin.py` (costing, alerts, jobs, pipeline, recorder, transform).
   8. `routers/payments.py` (x402 + paid endpoints).
   9. `routers/mcp.py` (merged from mcp_production.py's HTTP transport).
   10. `routers/auth.py` (auth, agency client auth, api key).
2. **Fix silent error swallowing (the 159 `except Exception`).** Move to `errors.py` hierarchy: `PryHTTPError`, `PryAuthError`, `PryScrapeError`, `PryStorageError`, etc. Use `logger.exception(...)` with request_id.
3. **Auth gate** — apply JWT/API-key middleware to all mutating endpoints except `/health`, `/live`, `/ready`, `/metrics`, `/docs`, `/openapi.json`, `/v1/templates/*`, `/v1/x402/pricing`. Move away from per-endpoint `@require_auth`.
4. **Deploy `mcp_production.py`** to Talos on `/srv/pry/mcp/` as a sibling server (port 8006). Update `docker-compose.yml`. Make `pry mcp serve` actually work (wire click dispatcher).
5. **Set `PRY_X402_WALLET` and `PRY_X402_FACILITATOR`** on Talos. Verify endpoints transition from 503 → 402 → 200.
6. **Add `routers/mcp.py` HTTP+SSE transport** to the main app (alternative to sibling process). Route `/sse`, `/messages/:sid`.
7. **Update `smithery.yaml` / `glama.json` / `pulsemcp.json`** with the live `mcp.pry.dev` URL and remove the suspended `cryptorugmuncher` GitHub URLs.

### Phase 4 — Apify launch (1.5 weeks, parallelizable with Phase 3)

Goal: Pry ships as an Apify Actor.

1. **Minimal Apify Actor (1 day)**:
   - `pip install apify>=2.0` (added in Phase 0).
   - `.actor/actor.json` — manifest.
   - `.actor/Dockerfile` — `FROM apify/actor-python-playwright:3.12-slim`, copy src/, pyproject, templates.
   - `src/main.py` — `async def main(): async with Actor: actor_input = await Actor.get_input(); ...; await Actor.push_data(...)`.
   - Write the input schema from `apify_schema.py` to `.actor/input_schema.json` via a `make actor-build` target.
2. **Strip local-only deps from the Actor image** — FlareSolverr (`docker-compose.yml`), Tor profile, depend on `curl_cffi` + `playwright` + cloudscraper + archive.org only.
3. **Push to Apify (1 day)** — `apify login`, `apify push`, verify `apify call` runs.
4. **Publish on Apify Store** — name `pry-scraper`, category "Developers", monetization via `apify monetize` (per-scrape pricing).
5. **Public listing (1 day)** — write actor description, screenshots, README. Submit to Apify for review.
6. **Actor README** — what inputs it accepts, what outputs it produces, error modes, examples.

### Phase 5 — Production polish + observability + tests (1.5 weeks)

Goal: ship-ready. 80% test coverage that's real, not theater. Observability that operations trusts.

1. **Real tests** — rewrite `test_advanced_scraping.py`, `test_referrals.py`, etc. to test BEHAVIOR not presence. Use `respx` for httpx mocking. Use `freezegun` for time-travel. Use `vcr.py` for recording live API calls.
2. **Coverage gate** — `--cov-fail-under=80` in `pyproject.toml [tool.coverage.run]`. CI fails below threshold.
3. **CI/CD** — split the single workflow into:
   - `lint.yml` (ruff + format check)
   - `typecheck.yml` (mypy strict, no disabled codes)
   - `test.yml` (pytest with respx, no real network; installs playwright + tesseract; coverage gate)
   - `security.yml` (bandit + pip-audit + gitleaks)
   - `docker.yml` (build + smoke)
   - `deploy.yml` (push to Talos, run healthcheck)
   - **Self-hosted runner** on [INTERNAL_HOST] — no GitHub Actions minutes.
4. **Observability** — wire OpenTelemetry OTLP exporter to a real backend (Grafana Cloud free tier, or local Tempo on Talos). Real distributed tracing across `httpx`, `playwright`, `db`.
5. **Structured logging** — JSON logs with `request_id`, `tenant_id`, `user_id`, `route`, `latency_ms`. Forward to Loki (free tier) or write to journald on Talos.
6. **OpenAPI SDK generation** — drop `pry_sdk.py` (130 LOC hand-maintained), generate `pry-sdk-python` from `openapi.json`. Generate `pry-sdk-js`. Publish to PyPI as `pry-scraper-sdk` and to npm as `@pry/sdk`.
7. **Deprecation log** — what was deleted in this rewrite:
   - `parser.py.tmp`
   - `stealth_engine.py`, `browser_pool.py`, `lazy_load.py`, `shadow_dom.py` (4 modules, ~518 LOC)
   - The 5 dead tiers in `ultimate_scraper.py`
   - The flaky `tests/test_api.py:46-69`
   - The 159 broad `except Exception`
   - The `.pry_sdk` reference
   - `data.db` orphan
8. **Decorate** — add `READY` / `LIVE` to README badges from `/health` and `/live` responses.

---

## 7. Apify-publishable cut (smallest viable for Apify)

If the only goal is "ship on Apify first, full production later", cut Phases 1, 3, 5 and just do:

| Task | Effort |
|---|---|
| Phase 0 stop-the-bleeding (3 days) | 3d |
| Phase 4 (all 1.5 weeks) | 7d |
| Phase 2 minimum: fix the missing deps, replace `stealth_engine.py` with `playwright-stealth`, drop the dead tiers | 4d |
| **Total** | **~2 weeks** for Apify-publishable |

Production polish follows the Apify launch. Pricing on Apify: per-scrape (e.g. $0.005/scrape, free monthly tier for viral growth).

---

## 8. The "2026 AI-Forward" code style we want

Distributed in the codebase by Phase 5. Reference for new modules:

```
pry/
├── README.md                       # honest, no hallucinated features
├── AGENTS.md
├── pyproject.toml                  # uv-managed, pinned
├── Dockerfile                      # apify/actor-python for Apify
├── .dockerignore
├── alembic/                        # NEW — migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── alembic.ini
├── src/
│   └── pry/                        # NEW — proper package layout
│       ├── __init__.py
│       ├── py.typed
│       ├── main.py                 # FastAPI entrypoint
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py              # FastAPI() instance only
│       │   ├── deps.py             # shared dependencies
│       │   ├── errors.py
│       │   ├── routers/            # one file per domain
│       │   │   ├── health.py
│       │   │   ├── scraping.py
│       │   │   ├── templates.py
│       │   │   ├── extraction.py
│       │   │   ├── sessions.py
│       │   │   ├── agents.py
│       │   │   ├── integrations.py
│       │   │   ├── compliance.py
│       │   │   ├── admin.py
│       │   │   ├── payments.py
│       │   │   ├── mcp.py
│       │   │   └── auth.py
│       │   ├── middleware/
│       │   │   ├── auth.py
│       │   │   ├── ratelimit.py
│       │   │   ├── request_id.py
│       │   │   ├── logging.py
│       │   │   └── errors.py
│       │   └── schemas/            # pydantic models per router
│       │       ├── scraping.py
│       │       └── ...
│       ├── core/                   # pure business logic, framework-free
│       │   ├── errors.py
│       │   ├── config.py
│       │   ├── logging.py
│       │   ├── http.py             # shared httpx + curl_cffi
│       │   └── secrets.py          # gopass + env
│       ├── scrape/                 # the scraping engine
│       │   ├── fallbacks.py        # 5-tier chain
│       │   ├── parsers.py          # pdf, docx, html
│       │   ├── extractor.py        # CSS + LLM fallback
│       │   ├── templates.py
│       │   └── monitor.py          # freshness, structure
│       ├── llm/                    # unified Ollama/OpenRouter client
│       │   ├── client.py
│       │   ├── extraction.py
│       │   ├── vision.py
│       │   └── schemas.py           # structured-output
│       ├── db/
│       │   ├── engine.py            # AsyncSession with aiosqlite/postgres
│       │   ├── migrations.py
│       │   ├── models.py
│       │   └── repos/               # one per model
│       ├── billing/                 # x402 implementation
│       │   ├── protocol.py
│       │   ├── middleware.py
│       │   └── ledger.py
│       ├── integrations/
│       │   ├── shopify.py
│       │   ├── woocommerce.py
│       │   ├── salesforce.py
│       │   ├── hubspot.py
│       │   ├── pipedrive.py
│       │   ├── close.py
│       │   ├── email.py            # Gmail/Outlook
│       │   ├── slack.py
│       │   └── webhook.py
│       ├── platforms/               # publish targets
│       │   ├── apify.py            # apify actor entrypoint
│       │   ├── cloudflare.py       # MCP worker
│       │   └── mcp.py              # JSON-RPC dispatcher
│       └── cli/
│           ├── __init__.py
│           └── main.py             # click-based, replaces cli.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── templates/                       # 110 JSON
├── TEMPLATES-COVERAGE.md           # NEW: honest coverage
├── docs/
└── .actor/                          # NEW: for Apify
```

**Key changes that make this 2026-current:**

1. **`src/` layout** — proper Python package, enables `pyproject.toml [tool.setuptools.packages.find]`, prevents import ambiguity.
2. **`py.typed` marker** — third-party users get type checking.
3. **`core/`** — framework-free business logic, testable without spinning up FastAPI.
4. **One router file per domain** — each < 500 LOC, one clear responsibility.
5. **`db/repos/` pattern** — every SQL call goes through a repo function. No `session_scope()` calls scattered through business logic.
6. **`middleware/`** explicit — auth, ratelimit, request_id, logging, error-handling all separate files.
7. **`llm/` separated from `core/`** — LLM extraction, vision, structured output are first-class concerns.
8. **`platforms/` separated from `integrations/`** — where we publish (Apify, Cloudflare, MCP server) is different from what we integrate with (Shopify, Salesforce).
9. **`alembic/` migrations** — version-controlled schema. No more `Base.metadata.create_all()`.
10. **`tests/unit/`, `tests/integration/`, `tests/e2e/`** — honest test layering.

---

## 9. Open-Source Install List (Phase-keyed)

### Phase 0 (3 days)
- `cloudscraper`, `aiohttp-socks[aiohttp]`, `undetected_chromedriver`, `pyjwt`, `apify>=2.0`
- `respx` (or `pytest-httpx`)
- `freezegun`

### Phase 1 (1.5 weeks)
- `alembic`
- `aiosqlite` is already installed; just import it

### Phase 2 (1.5 weeks)
- `playwright-stealth`
- `curl_cffi` is already installed; use it
- `sentence-transformers` (for real embeddings) — or drop embedding fallback

### Phase 3 (2 weeks)
- `fastapi[all]` (orjson, asyncpg, jinja2 extras)

### Phase 4 (1.5 weeks, parallelizable)
- `apify` (added in Phase 0)

### Phase 5 (1.5 weeks)
- `pip-audit`
- `vcr.py` or `pytest-recording`
- `mutmut` or `cosmic-ray`
- `pytest-benchmark` (perf gates)
- OpenTelemetry OTLP exporter
- `uv` (replaces pip)
- `pre-commit` cache, `act`

---

## 10. KPIs / Definition of Done

| KPI | Today | Target at end of Phase 5 |
|---|---|---|
| Tests passing | 498/500 (2 flaky) | 800+/800 stable |
| Test coverage | 60% (no gate) | ≥ 80% (CI gated) |
| Endpoints with auth | 2/~190 | all mutating |
| Endpoints with rate-limit | ~6 | all |
| Endpoints with structured logging | 0 | all |
| Endpoints with tracing | 0 | all |
| Dead code (LOC) | ~700 (orphaned modules) + ~2,000 (hallucinated features) | <100 |
| Anti-detection fallback tiers working end-to-end | 5/10 | 5/5 (consolidated) |
| Templates passing live-URL test | ~21-30 | 50+ |
| Concurrent writers without corruption | NO | YES (atomic+locked or SQLite) |
| Schema migrations | Hand-edit or wipe | Alembic, versioned |
| CI minutes burned | GitHub-hosted ($$) | Self-hosted Talos ($0) |
| Deployable to Apify store | NO | YES |
| Production uptime | TBD | 99.5% / 30d rolling |
| p95 latency (scrape) | TBD | < 5s for direct, < 30s with playwright |

---

## 11. What to do **tomorrow** (1 working day)

If the user picks one day to make Pry significantly better:

1. Delete `parser.py.tmp` (5 min)
2. Fix `cli.py:339-340` infinite recursion (15 min)
3. Add missing deps to `pyproject.toml`: `cloudscraper`, `aiohttp-socks[aiohttp]`, `undetected_chromedriver`, `pyjwt`, `apify>=2.0` (10 min)
4. Fix `docker-compose.yml:18` env var name (2 min)
5. Fix `Dockerfile` healthcheck to not use `curl` (10 min)
6. Add `USER` directive to `Dockerfile` (5 min)
7. Fix `tests/test_api.py:46-69` to mock `PryScraper` (15 min)
8. Fix `ultimate_scraper.py:33-46` docstring to honest 5-tier (10 min)
9. Migrate `quality.py:347` from JSON to SQLite via existing `QualityCheck` model (already in `db.py:197`) (1 hr)
10. Same for `freshness.py` (1 hr)
11. Pin `uv.lock` (30 min)
12. Set `--cov-fail-under=60` to start (we can tighten later) (5 min)

End of day: **no flaky tests, no infinite recursion, no dead tiers claiming to work, no JSON races on `quality/freshness`, real coverage gate, Dockerfile runs as non-root.**

That's the user's "day to make Pry significantly better" answer. Then Phase 0 takes another 2 days, then Phase 1 starts. Apify-publishable in 2 weeks.

---

## 12. Risks

1. **Phase 2 anti-detection consolidation** — by removing 7 modules, we lose the "kitchen sink" cover. Mitigation: keep `camoufox_integration.py` and `cookie_warmer.py` as opt-in endpoints (operators can call them manually for hard cases).
2. **Phase 3 router split** — risk of breaking existing endpoints. Mitigation: split one router at a time, deploy each, run smoke test (`curl /health` + 1 representative endpoint per router).
3. **Phase 4 Apify first-impressions** — Apify Store review takes 1-2 weeks. Start early; in parallel with Phase 1/2.
4. **Phase 5 self-hosted CI runner** — Talos has other workloads; registering a runner should not consume > 10% CPU. Run on Hydra if Talos is busy.
5. **Multi-worker with cookies/sessions** — moving from JSON files to SQLite is the easy part. Sharing browser sessions across workers requires Redis or sticky sessions. Defer to v3.1.
6. **OpenAI/Anthropic rate limits** — depending on LLM extraction (real, not regex) means we burn keys. Mitigation: local Ollama first; OpenAI only on cache-miss.

---

## 13. Decision log (what this audit is committing to)

- **ADR-0003**: Consolidate anti-detection to `curl_cffi` + `playwright-stealth`. Delete 7 orphan modules.
- **ADR-0004**: SQLite for single-node, Postgres for multi-host. Alembic for migrations. Atomic writes everywhere.
- **ADR-0005**: `src/pry/` layout. One router per domain. No file > 500 LOC (enforced by CI).
- **ADR-0006**: Real LLM extraction by default — Ollama first, OpenRouter fallback. Regex fallback only on cache-miss + LLM error.
- **ADR-0007**: JWT auth + per-tenant quota on all mutating endpoints. `/health` and `/metrics` public.
- **ADR-0008**: Apify is the primary distribution post-Phase 4. Self-hosted Talos deploy remains supported.
- **ADR-0009**: Tests must mock network (`respx`) and time (`freezegun`). No real network in CI.
- **ADR-0010**: Coverage gate `--cov-fail-under=80` after Phase 5. No merging below threshold.
- **ADR-0011**: Self-hosted CI runner on Talos. No GitHub Actions minutes.
- **ADR-0012**: OpenTelemetry OTLP exporter. Loki for logs. Prometheus for metrics. Grafana dashboards on Grafana Cloud (free) or Talos.

---

## 14. Links

- Original audit (2026-06-30, Sonnet 4.5): `AUDIT.md`
- This audit (2026-07-06): `AUDIT-2026-Q3.md`
- Production roadmap: `PRODUCTION-PLAN.md` (this file)
- Status: `STATUS.md`
- Sprint plan: `PLAN.md`
- AGENTS contract: `AGENTS.md`
- Standards: https://git.rugmunch.io/RugMunchMedia/standards
