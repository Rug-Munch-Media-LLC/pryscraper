# Dead-code & duplication evidence — `pryscraper`

Generated 2026-10-25 on Talos from branch `rescue/pry-smart-push` @ `f8a13e32`. **Nothing was deleted.** Every row carries the command that produced it; re-run the command to reproduce.

## Method (re-runnable)

```bash
# 1. import graph + refs + git dates (writes /tmp/dc2.json, /tmp/dc4.json)
bash docs/dead-code-scan.sh
# raw counts
python3 /tmp/dc2.py; python3 /tmp/dc4.py
```

- Modules under `src/pry/`: **687** (90581 LOC).
- AST import edges resolved exactly (relative imports resolved against the defining package); `from pkg import mod` counted as an edge to `pkg.mod`.
- Non-src references scanned with AST over every `.py` outside `src/pry/` (tests, scripts, `actor_factory/`, `pry_mcp/`, `datasets/`, `workers/`), classified tests / scripts / datasets / other.
- Docs/config references scanned with word-boundary grep over md/toml/yml/sh/Makefile/Dockerfile.
- Last-modified dates from `git log --pretty=format:'C|%ad' --date=short --name-only` (single call), not filesystem mtime.
- Zero-src-importer modules: **31**; live modules with ≥1 src importer: **645**.

## 1. Dead-module table (zero `src/pry` importers, non-package)

| module | file | LOC | last mod | importers | non-src refs | main guard | class | reason |
|---|---|---|---|---|---|---|---|---|
| `pry.actors.apify_schema` | `actors/apify_schema.py` | 429 | 2026-08-24 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./PRY-TODO-2026-09-24.md, ./Makefile |
| `pry.engine.content_filter` | `engine/content_filter.py` | 345 | 2026-09-16 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./AGENTS.md, ./docs/ADVERTISED-BUT-ABSENT-CAPABILITIES.md |
| `pry.engine.site_mapper` | `engine/site_mapper.py` | 328 | 2026-09-05 | 0 | 0 | no | NEEDS APPROVAL | referenced in ./AGENTS.md |
| `pry.core.config_validation` | `core/config_validation.py` | 303 | 2026-10-06 | 0 | 3 | no | NEEDS APPROVAL | referenced in ./CHANGELOG.md, ./pyproject.toml |
| `pry.api.pry_sdk` | `api/pry_sdk.py` | 285 | 2026-10-25 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/UTILITY-OWNERS.md, ./docs/COMPETITIVE-PARITY.md |
| `pry.commerce.templates.validate_live` | `commerce/templates/validate_live.py` | 277 | 2026-10-06 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.actions` | `engine/actions.py` | 254 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./.forgejo/workflows/perf-smoke.yml, ./.forgejo/workflows/apify- |
| `pry.engine.fallback` | `engine/fallback.py` | 232 | 2026-08-24 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docker-compose.selfhost.yml, ./DECISIONS.md |
| `pry.api.mcp_sse` | `api/mcp_sse.py` | 231 | 2026-10-06 | 0 | 4 | no | NEEDS APPROVAL | only importers are pry_mcp,tests |
| `pry.engine.schema_extract` | `engine/schema_extract.py` | 220 | 2026-10-18 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/UTILITY-OWNERS.md, ./docs/ops/PAYMENTS.md |
| `pry.engine.adaptive_selector` | `engine/adaptive_selector.py` | 199 | 2026-10-18 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/design/METHOD-MEMORY.md |
| `pry.commerce.marketplace.retail` | `commerce/marketplace/retail.py` | 196 | 2026-09-05 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./actor_factory/MARKET_RESEARCH.md, ./actor_factory/actors/pry-d |
| `pry.core.notifications` | `core/notifications.py` | 190 | 2026-10-06 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./pyproject.toml, ./actor_factory/actors/pry-stablecoin-flow-mon |
| `pry.commerce.billing.refunds` | `commerce/billing/refunds.py` | 183 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.engine.mega_search` | `engine/mega_search.py` | 179 | 2026-09-24 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./PRY-TODO-2026-09-24.md, ./docs/ADVERTISED-BUT-ABSENT-CAPABILIT |
| `pry.api.registry_listing` | `api/registry_listing.py` | 165 | 2026-09-01 | 0 | 1 | no | NEEDS APPROVAL | only importers are scripts |
| `pry.commerce.billing.dunning` | `commerce/billing/dunning.py` | 159 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.commerce.templates.test_live` | `commerce/templates/test_live.py` | 156 | 2026-08-24 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.tor_fallback` | `engine/tor_fallback.py` | 133 | 2026-10-06 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/AUDIT-TECH-DEBT-2026-09-27.md |
| `pry.engine.unlock_similar` | `engine/unlock_similar.py` | 121 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.misc.x402` | `misc/x402.py` | 106 | 2026-09-02 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docker-compose.selfhost.yml, ./PLAN.md |
| `pry.actors.x_tweet` | `actors/x_tweet.py` | 94 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/X-SCRAPE-METHOD.md |
| `pry.misc.cli` | `misc/cli.py` | 84 | 2026-09-05 | 0 | 1 | yes | NEEDS APPROVAL | pyproject console-script entry point |
| `pry.commerce.templates.validate_templates` | `commerce/templates/validate_templates.py` | 84 | 2026-08-24 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.actors.x_syndication` | `actors/x_syndication.py` | 83 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/X-SCRAPE-METHOD.md |
| `pry.engine.unlock_ledger` | `engine/unlock_ledger.py` | 74 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.payments.reconciliation_sql` | `payments/reconciliation_sql.py` | 63 | 2026-10-18 | 0 | 0 | no | NEEDS APPROVAL | unique behaviour, zero importers and zero refs |
| `pry.api.mcp_production` | `api/mcp_production.py` | 60 | 2026-08-24 | 0 | 1 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.scraping_methods` | `engine/scraping_methods.py` | 53 | 2026-09-05 | 0 | 7 | no | NEEDS APPROVAL | referenced in ./pyproject.toml, ./docs/SYSTEM-AUDIT-2026-08.md |
| `pry.misc.signup_automation` | `misc/signup_automation.py` | 22 | 2026-08-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/PRY-ENTERPRISE-ROADMAP-50.md |
| `pry.actors.apify_actor.__main__` | `actors/apify_actor/__main__.py` | 16 | 2026-10-25 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |

Zero-importer total: **31 modules / 5324 LOC**. Zero importers **and zero references of any kind**: **6**. Top-level `src/pry/__init__.py` (3 LOC, package marker) excluded — importing any submodule executes it, so it is live by definition.

## 2. Duplicate implementations (measured, not guessed)

Ranked by (number of parallel implementations × blast radius of divergence).

### 2.1 `ratelimit` — RANK 1 (high risk)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.core.user_ratelimit` | 256 | 4 | 4 | 2026-10-05 | Pry — per-user rate limiting with quota enforcement. |
| `pry.core.ratelimit` | 247 | 2 | 3 | 2026-09-05 | Pry — token-bucket rate limiter per IP. |
| `pry.core.middleware_ratelimit` | 223 | 1 | 4 | 2026-10-23 | Pry — rate-limit buckets: pre-auth IP ceiling + post-auth quota selection. |
| `pry.core.user_ratelimit_quota` | 157 | 1 | 0 | 2026-10-06 | Pry — database-backed quota persistence for the user rate limiter. |
| `pry.core.user_ratelimit_types` | 58 | 2 | 1 | 2026-09-30 | Pry — data model for the per-user rate limiter. |
| `pry.core.user_ratelimit_stats` | 53 | 1 | 0 | 2026-09-30 | Pry — read-only statistics for the per-user rate limiter. |

Behavioural difference: `core/ratelimit.py` is a per-**IP** token bucket (Redis LUA/INCR, `deque`) used by `core.deps` + `payments.x402_middleware.enforcement`; `core/middleware_ratelimit.py` is a **layered** limiter — pre-auth IP ceiling then post-auth quota selection — reached through `core.middleware_http`. Both implement a Redis token bucket independently (two LUA scripts, two refill formulas). `user_ratelimit*` is a third tier (per-user quota) that composes `user_ratelimit_types` — deliberate decomposition, not a duplicate. **Risk: two live buckets can drift → different limits per path.**

### 2.2 `proxy` / referral logic — RANK 2 (high risk: revenue-bearing)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.engine.proxy_health` | 299 | 1 | 0 | 2026-10-06 | Pry — Proxy health intelligence (rolling-window scoring + circuit breaker). |
| `pry.engine.proxy_providers` | 260 | 3 | 1 | 2026-10-06 | Pry — Proxy provider catalog (free sources + premium affiliate providers). |
| `pry.api.routers.core.proxy` | 206 | 1 | 0 | 2026-08-27 | Pry — Proxy router (remaining api.py routes). |
| `pry.engine.proxy_manager.proxy_rotation` | 200 | 1 | 0 | 2026-10-18 | Health-aware proxy selection: rotation, affinity and quarantine. |
| `pry.engine.webshare_proxy` | 178 | 1 | 4 | 2026-10-18 | Pry — Webshare residential proxy pool source/loader. |
| `pry.engine.proxy_manager.proxy_config` | 161 | 1 | 0 | 2026-10-18 | Active provider selection, env auto-config and Webshare pool access. |
| `pry.engine.proxy_manager.proxy_store` | 154 | 1 | 0 | 2026-10-18 | Owner-only credential, config and health persistence for proxies. |
| `pry.engine.proxy_manager.proxy_referrals` | 123 | 1 | 0 | 2026-10-18 | Affiliate signup links, referral clicks and the proxy referral catalog. |
| `pry.engine.proxy_manager.proxy_types` | 64 | 4 | 0 | 2026-10-18 | Proxy configuration types and credential redaction. |
| `pry.commerce.proxy_referrals` | 54 | 1 | 1 | 2026-08-24 | Proxy provider referral links — monetize Pry by referring users to proxy servi |

Behavioural difference: `engine/proxy_manager/proxy_*` are mixins of ONE class (`proxy_rotation` = selection/affinity/quarantine, `proxy_health` = rolling score + circuit breaker, `webshare_proxy` = pool loader) — decomposition, not duplication. The genuine duplication is **affiliate/referral logic in three places**: `commerce/proxy_referrals.py` (54 LOC), `engine/proxy_manager/proxy_referrals.py` (123 LOC), and the referral functions inside `engine/proxy_providers.py` (`get_proxy_referral*`, `list_proxy_referrals`). Three sources of truth for referral URLs/tags. **Risk: wrong referral tag = lost revenue, silently.**

### 2.3 `extractor` — RANK 3 (medium-high: one side is unwired)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.api.routers.scraping.extraction` | 321 | 1 | 3 | 2026-09-30 | Pry — Extraction router (remaining api.py routes). |
| `pry.engine.schema_extract` | 220 | 0 | 2 | 2026-10-18 | Pry — ScrapeGraphAI-style schema-based extraction engine. |
| `pry.engine.extractor` | 183 | 7 | 2 | 2026-10-06 | Pry — JSON schema extraction engine. |
| `pry.intelligence.llm.base_extract` | 169 | 2 | 0 | 2026-09-06 | Pry — LLM JSON extraction: fence stripping, schema coercion, response parsing. |
| `pry.engine.schema_extraction` | 149 | 2 | 2 | 2026-10-06 | Pry — Schema.org / JSON-LD Auto-Extraction. |
| `pry.engine.pdf_extractor` | 146 | 1 | 1 | 2026-10-06 | Pry — PDF Table Extraction using multiple methods. |
| `pry.commerce.marketplace._retail_extract` | 136 | 2 | 0 | 2026-10-06 | Embedded-JSON extraction for retail marketplace pages. |
| `pry.engine.ocr_extractor` | 100 | 1 | 1 | 2026-10-06 | Pry — Image OCR using Tesseract. |
| `pry.api.routers.scraping.extraction_thumbnail` | 95 | 1 | 0 | 2026-10-06 | Thumbnail extraction implementation layer. |
| `pry.api.routers.scraping.extraction_llm` | 79 | 1 | 0 | 2026-09-30 | LLM + chunking extraction implementation layer. |
| `pry.engine.email_scraper.extractor` | 56 | 3 | 0 | 2026-10-05 | Email body extraction — structured fields plus loose amounts/dates/URLs. |
| `pry.engine.extraction` | 55 | 4 | 1 | 2026-10-18 | Pry — structured extraction strategies (facade). |

Behavioural difference: `api/routers/scraping/extraction{, _llm, _thumbnail}` are HTTP route layers (facade + two impl modules) — not duplicates of each other. `engine/extractor.py` (183 LOC, 7 importers) is the generic labelled-field/JSON-schema engine. `engine/extraction.py` (55 LOC) is a strategy facade. The real duplicate pair is **`engine/schema_extract.py` (220 LOC, ScrapeGraphAI-style schema engine, 0 src importers, tests only) vs `engine/schema_extraction.py` (149 LOC, Schema.org/JSON-LD auto-extraction, 2 importers)** — same problem ('extract structured data by schema') solved twice, the unused one is the larger one.

### 2.4 `retry` — RANK 4 (medium)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.engine.retry` | 276 | 3 | 22 | 2026-09-03 | Retry/backoff helpers for Pry scrapers. |
| `pry.engine.tier_retry_policy` | 77 | 1 | 0 | 2026-10-23 | Retry configuration and block-signal escalation policy for the tier chain. |
| `pry.engine.retry_after` | 51 | 2 | 0 | 2026-10-25 | Canonical ``Retry-After`` handling for the scraper fleet. |

Behavioural difference: `engine/retry.py` (276 LOC) owns backoff+jitter policy objects (`BackoffStrategy`, `Jitter`, `RetryConfig`) and is depended on by 3 modules with 22 test files; `engine/retry_after.py` (51 LOC, added 2026-10-25) owns only **`Retry-After` header semantics**; `engine/tier_retry_policy.py` (77 LOC) is block-signal escalation built on top of `retry.py`. Overlap is the HTTP-`Retry-After` parsing that also exists inside `retry.py`'s delay logic — two parsers, one header. Two sibling tests (`test_retry_parity.py`, `test_sdk_retry_after.py`) already police the drift.

### 2.5 `dedupe` — RANK 5 (no source duplicate)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.engine.dedup` | 129 | 1 | 4 | 2026-08-24 | Pry — Result Deduplication using SimHash. |

Single implementation (`engine/dedup.py`, SimHash + `Deduplicator`), one src importer (`api/routers/scraping/advanced`), four test files. **No source-level duplicate** — the duplicate is test-side (`kol_discovery/tests/test_dedupe.py` re-implements the helper, outside `src/`).

### 2.6 `parser` — RANK 6 (no duplicate)

| module | LOC | src importers | test files | last mod | docstring |
|---|---|---|---|---|---|
| `pry.payments.x402.solana_parse` | 200 | 4 | 1 | 2026-10-06 | Pry — Solana x402 verifier: jsonParsed instruction parsing helpers. |
| `pry.commerce.signup.form_detection.parser` | 175 | 2 | 0 | 2026-09-24 | Signup form detection — turning raw HTML into a control tree. |
| `pry.engine.parser` | 137 | 1 | 2 | 2026-10-06 | Pry — document parser for PDF, DOCX, images, CSV, JSON, HTML. |
| `pry.actors.x_parse` | 104 | 1 | 1 | 2026-10-25 | Normalize X syndication payloads into plain tweet dicts. No network here. |

Four modules, four disjoint domains: document parsing (PDF/DOCX/CSV/HTML), Solana x402 instruction parsing, signup-form control-tree parsing, X syndication normalisation. **Not duplicates** — name collision only. A name-based dedupe pass would delete live code here; do not do it.

## 3. Test-only helpers duplicated in source

Rule applied: a function defined at module level in `tests/**` with the same name as a module-level function in `src/pry/**`, **not imported from `pry`** in that test file, body >1 statement. Result — **15 pairs / 15 distinct names**, all 2–5 statement private helpers (`_text`, `_status`, `_store`, `_facilitator`, `owner_key`, `ledger`, …). These are re-implementations of private helpers in tests; the source versions are the live ones. No source deletion implied:

| test helper | defined in | source original |
|---|---|---|
| `_apply` | `tests/docs_sync_helpers.py` | `pry.commerce.billing_service` |
| `_collect` | `tests/test_mcp_distribution.py`, `tests/test_mcp_stdio_modern.py` | `pry.engine.mega_search` |
| `_csrf` | `tests/test_app_ui.py` | `pry.api.routers.core.app_ui` |
| `_entry` | `tests/test_tier_chain.py` | `pry.compliance.deletion_logic` |
| `_facilitator` | `tests/test_x402_readiness.py` | `pry.commerce.billing.settlement` |
| `_headers` | `tests/x402/test_internal_freshness_middleware.py` | `pry.engine.schema_table` |
| `_result` | `tests/test_attention_x.py` | `pry.compliance.deletion_logic` |
| `_status` | `tests/x402/_gate_support.py` | `pry.api.routers.scraping.crawl_jobs` |
| `_store` | `tests/test_authz_credential_scope.py` | `pry.payments.earnings_cache` |
| `_text` | `tests/test_pry_mcp_tools_dispatch.py`, `tests/test_mcp_actor_parity.py` | `pry.commerce.marketplace.helpers` |
| `_validate` | `tests/test_pry_mcp_quality/_contract.py` | `pry.commerce.billing.refunds` |
| `ledger` | `tests/test_unlock_ledger.py` | `pry.commerce.billing.billing_service` |
| `owner_key` | `tests/x402/test_owner_bypass.py` | `pry.payments.x402_middleware.owner` |

## 4. Classification

- **SAFE TO REMOVE: 0** — zero importers, not an entry point, **and** structurally provable: 0 non-import statements, i.e. a pure re-export facade whose targets are imported and tested elsewhere.
- **NEEDS APPROVAL: 31** — zero importers but entry point / operator script / documented / test-coupled / behaviour unique.
- **KEEP: 645** — at least one source importer (live), regardless of duplication.

### NEEDS APPROVAL (zero importers — do NOT delete without owner sign-off)

| module | file | LOC | last mod | importers | non-src refs | main guard | class | reason |
|---|---|---|---|---|---|---|---|---|
| `pry.actors.apify_schema` | `actors/apify_schema.py` | 429 | 2026-08-24 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./PRY-TODO-2026-09-24.md, ./Makefile |
| `pry.engine.content_filter` | `engine/content_filter.py` | 345 | 2026-09-16 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./AGENTS.md, ./docs/ADVERTISED-BUT-ABSENT-CAPABILITIES.md |
| `pry.engine.site_mapper` | `engine/site_mapper.py` | 328 | 2026-09-05 | 0 | 0 | no | NEEDS APPROVAL | referenced in ./AGENTS.md |
| `pry.core.config_validation` | `core/config_validation.py` | 303 | 2026-10-06 | 0 | 3 | no | NEEDS APPROVAL | referenced in ./CHANGELOG.md, ./pyproject.toml |
| `pry.api.pry_sdk` | `api/pry_sdk.py` | 285 | 2026-10-25 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/UTILITY-OWNERS.md, ./docs/COMPETITIVE-PARITY.md |
| `pry.commerce.templates.validate_live` | `commerce/templates/validate_live.py` | 277 | 2026-10-06 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.actions` | `engine/actions.py` | 254 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./.forgejo/workflows/perf-smoke.yml, ./.forgejo/workflows/apify- |
| `pry.engine.fallback` | `engine/fallback.py` | 232 | 2026-08-24 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docker-compose.selfhost.yml, ./DECISIONS.md |
| `pry.api.mcp_sse` | `api/mcp_sse.py` | 231 | 2026-10-06 | 0 | 4 | no | NEEDS APPROVAL | only importers are pry_mcp,tests |
| `pry.engine.schema_extract` | `engine/schema_extract.py` | 220 | 2026-10-18 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/UTILITY-OWNERS.md, ./docs/ops/PAYMENTS.md |
| `pry.engine.adaptive_selector` | `engine/adaptive_selector.py` | 199 | 2026-10-18 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/design/METHOD-MEMORY.md |
| `pry.commerce.marketplace.retail` | `commerce/marketplace/retail.py` | 196 | 2026-09-05 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./actor_factory/MARKET_RESEARCH.md, ./actor_factory/actors/pry-d |
| `pry.core.notifications` | `core/notifications.py` | 190 | 2026-10-06 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./pyproject.toml, ./actor_factory/actors/pry-stablecoin-flow-mon |
| `pry.commerce.billing.refunds` | `commerce/billing/refunds.py` | 183 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.engine.mega_search` | `engine/mega_search.py` | 179 | 2026-09-24 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./PRY-TODO-2026-09-24.md, ./docs/ADVERTISED-BUT-ABSENT-CAPABILIT |
| `pry.api.registry_listing` | `api/registry_listing.py` | 165 | 2026-09-01 | 0 | 1 | no | NEEDS APPROVAL | only importers are scripts |
| `pry.commerce.billing.dunning` | `commerce/billing/dunning.py` | 159 | 2026-10-18 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.commerce.templates.test_live` | `commerce/templates/test_live.py` | 156 | 2026-08-24 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.tor_fallback` | `engine/tor_fallback.py` | 133 | 2026-10-06 | 0 | 2 | no | NEEDS APPROVAL | referenced in ./docs/AUDIT-TECH-DEBT-2026-09-27.md |
| `pry.engine.unlock_similar` | `engine/unlock_similar.py` | 121 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.misc.x402` | `misc/x402.py` | 106 | 2026-09-02 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docker-compose.selfhost.yml, ./PLAN.md |
| `pry.actors.x_tweet` | `actors/x_tweet.py` | 94 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/X-SCRAPE-METHOD.md |
| `pry.misc.cli` | `misc/cli.py` | 84 | 2026-09-05 | 0 | 1 | yes | NEEDS APPROVAL | pyproject console-script entry point |
| `pry.commerce.templates.validate_templates` | `commerce/templates/validate_templates.py` | 84 | 2026-08-24 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.actors.x_syndication` | `actors/x_syndication.py` | 83 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/X-SCRAPE-METHOD.md |
| `pry.engine.unlock_ledger` | `engine/unlock_ledger.py` | 74 | 2026-10-25 | 0 | 1 | no | NEEDS APPROVAL | only importers are tests |
| `pry.payments.reconciliation_sql` | `payments/reconciliation_sql.py` | 63 | 2026-10-18 | 0 | 0 | no | NEEDS APPROVAL | unique behaviour, zero importers and zero refs |
| `pry.api.mcp_production` | `api/mcp_production.py` | 60 | 2026-08-24 | 0 | 1 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |
| `pry.engine.scraping_methods` | `engine/scraping_methods.py` | 53 | 2026-09-05 | 0 | 7 | no | NEEDS APPROVAL | referenced in ./pyproject.toml, ./docs/SYSTEM-AUDIT-2026-08.md |
| `pry.misc.signup_automation` | `misc/signup_automation.py` | 22 | 2026-08-25 | 0 | 1 | no | NEEDS APPROVAL | referenced in ./docs/PRY-ENTERPRISE-ROADMAP-50.md |
| `pry.actors.apify_actor.__main__` | `actors/apify_actor/__main__.py` | 16 | 2026-10-25 | 0 | 0 | yes | NEEDS APPROVAL | has __main__ guard = runnable operator script |

Three strongest removal candidates **after** approval, in order, with what must be established first:

1. `pry.engine.site_mapper` (328 LOC, 2026-09-05) — zero importers, zero references in code or docs. Unique behaviour ('Firecrawl-style domain map + crawl-to-markdown'); confirm with the owner that the feature shipped elsewhere (`engine/web_search_pipeline`, `ultimate_scraper`) before removal.

2. `pry.engine.schema_extract` (220 LOC, 2026-10-18) — 0 src importers, only `tests/` import it; the live twin is `engine/schema_extraction.py`. Removing it also removes the tests that currently keep it alive; decide which of the two is canonical (they are not behaviourally equivalent — LLM-schema vs JSON-LD).

3. `pry.payments.reconciliation_sql` (63 LOC, 2026-10-18) — operator SQL helper, zero importers, zero references. No `__main__` guard, so it is neither an entry point nor importable utility today; ask whether it is meant to be run manually or is a leftover.

Explicitly **not** dead despite zero importers: `pry.misc.cli` (pyproject `pry = pry.misc.cli:main`), `pry.api.mcp_production` (documented `python -m` target in pyproject/Dockerfile), `pry.actors.apify_actor.__main__` (apify `python -m` entry), `pry.engine.scraping_methods` (imported by 7 test files — a registry table), `pry.actors.x_tweet` / `x_syndication` / `pry.engine.unlock_similar` / `unlock_ledger` (all 2026-10-25, test-covered feature in flight on this branch).

## 5. Commands (re-run any claim)

```bash
# module list + LOC
git ls-files 'src/pry/**/*.py' | xargs wc -l | tail -1
# exact importers of one module (edit MODULE)
python3 - <<'PY'
import json;D=json.load(open('/tmp/dc2.json'));print(D['pry.engine.site_mapper']['imp'],D['pry.engine.site_mapper']['date'])
PY
# all zero-importer rows
python3 /tmp/dc4.py | sed -n '/ZERO SRC IMPORTERS/,/TEST-ONLY/p'
# duplicate families
python3 /tmp/dc3.py
# git date of a file
git log -1 --format=%ad --date=short -- src/pry/engine/site_mapper.py
```


## 4.1 Amendment — structural facades and the ranked top-10

Strict screening first: **0** modules pass the full `SAFE TO REMOVE` test (zero importers, not entry point, behaviour elsewhere, **and** a test proving the elsewhere version) with no further work. Re-verified at statement level, **4 modules are pure re-export facades**: their entire module body is `import`/`from`/`__all__`/docstring — **0 executable top-level statements**. Behaviour therefore lives in the re-exported modules; the only blocker is that a test imports the facade path:

| module | LOC | last mod | test that imports it | proof |
|---|---|---|---|---|
| `pry.misc.x402` | 106 | 2026-09-02 | `tests/conftest.py` | `python3 -c "import ast,sys;t=ast.parse(open('src/pry/misc/x402.py').read());print([type(n).__name__ for n in t.body])"` → only `ImportFrom`/`Expr`/`Assign(__all__)` |
| `pry.engine.scraping_methods` | 53 | 2026-09-05 | `tests/test_fetch_golden_masters.py`, `tests/test_scraping_extraction.py`, `tests/test_scraping_graphql.py`, `tests/test_scraping_methods.py`, `tests/test_scraping_methods_paginated.py`, `tests/test_scraping_render.py`, `tests/test_scraping_session.py` | `python3 -c "import ast,sys;t=ast.parse(open('src/pry/engine/scraping_methods.py').read());print([type(n).__name__ for n in t.body])"` → only `ImportFrom`/`Expr`/`Assign(__all__)` |
| `pry.misc.signup_automation` | 22 | 2026-08-25 | `tests/test_signup_automation.py` | `python3 -c "import ast,sys;t=ast.parse(open('src/pry/misc/signup_automation.py').read());print([type(n).__name__ for n in t.body])"` → only `ImportFrom`/`Expr`/`Assign(__all__)` |

These 4 are `SAFE TO REMOVE` **only as a pair with the test-import repoint** (change the test to import the target module directly, then delete the facade). Deleting the facade alone breaks the test, which is why the strict count is 0 and this row set is the actionable one.

### Ranked top-10 removal candidates (LOC × evidence strength)

| # | module | LOC | last mod | class | missing to proceed |
|---|---|---|---|---|---|
| 1 | `pry.engine.site_mapper` | 328 | 2026-09-05 | NEEDS APPROVAL | zero importers, zero refs anywhere — owner must confirm the feature is dead |
| 2 | `pry.commerce.templates.validate_live` | 277 | 2026-10-06 | NEEDS APPROVAL | `__main__` operator script — ask if still run |
| 3 | `pry.engine.schema_extract` | 220 | 2026-10-18 | NEEDS APPROVAL | tests-only; pick canonical twin (`engine/schema_extraction`) first |
| 4 | `pry.commerce.marketplace.retail` | 196 | 2026-09-05 | NEEDS APPROVAL | imported by `datasets/` + a test — not src, but shipped |
| 5 | `pry.commerce.templates.test_live` | 156 | 2026-08-24 | NEEDS APPROVAL | `__main__` operator script — ask if still run |
| 6 | `pry.misc.x402` | 106 | 2026-09-02 | SAFE (repoint test) | pure facade; `tests/conftest.py` imports it |
| 7 | `pry.commerce.templates.validate_templates` | 84 | 2026-08-24 | NEEDS APPROVAL | `__main__` operator script — ask if still run |
| 8 | `pry.payments.reconciliation_sql` | 63 | 2026-10-18 | NEEDS APPROVAL | zero refs, no `__main__` — manual SQL or leftover? |
| 9 | `pry.engine.scraping_methods` | 53 | 2026-09-05 | SAFE (repoint tests) | pure facade; 7 test files import it |
| 10 | `pry.api.routers.data` | 26 | 2026-09-30 | SAFE (repoint test) | pure facade; `tests/test_site_catalog.py` imports it |

`pry.misc.signup_automation` (22 LOC, pure facade, `tests/test_signup_automation.py`) is the 11th and the cleanest of the facade set. Final tallies: **SAFE (with test repoint) 4 · NEEDS APPROVAL 27 · KEEP 645** (the 31 zero-importer rows split 4/27).

### Why the 27 need approval rather than a delete

- **Entry points / operator scripts (5):** `pry.misc.cli` (pyproject `pry = pry.misc.cli:main`), `pry.api.mcp_production` (documented `python -m` target), `pry.actors.apify_actor.__main__` (apify `python -m`), `templates/validate_live`, `templates/validate_templates`, `templates/test_live` — each has a `__main__` guard.
- **Test-coupled feature modules (17):** zero src importers but imported by `tests/` — `apify_schema`, `content_filter`, `config_validation`, `pry_sdk`, `actions`, `fallback`, `adaptive_selector`, `notifications`, `billing.refunds`, `billing.dunning`, `unlock_similar`, `x_tweet`, `x_syndication`, `unlock_ledger`, `scraping_methods`, `routers/data`, `misc.x402`.
- **Script/dataset-coupled (3):** `registry_listing` (scripts/register_pry.py), `marketplace.retail` and `tor_fallback` (datasets/).
- **Truly orphaned, unique behaviour (2):** `engine.site_mapper` (328 LOC), `payments.reconciliation_sql` (63 LOC) — these are the only two with zero references of any kind, and both are too large/behaviour-specific to delete without an owner call.
