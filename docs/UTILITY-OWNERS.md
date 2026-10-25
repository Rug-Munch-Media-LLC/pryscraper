# Utility owners — rate limit / retry / dedupe / extract

Status: proposal, 2026-10-25. Source of truth for "which copy is canonical".
Repos audited at `forgejo/main`: pryscraper `13fb8b80`, rugbrain `3f258f7`, rmi-backend `d11949c0`.

## 1. Inventory (measured)

| Capability | Copies | Files (lines) |
|---|---|---|
| rate limit | 19 files / 3,631 lines | pry: `core/ratelimit.py` 249, `core/middleware_ratelimit.py` 225, `core/user_ratelimit.py` 260, `core/user_ratelimit_quota.py` 157, `core/user_ratelimit_stats.py` 53, `core/user_ratelimit_types.py` 58 · rmi: `core/rate_limiter.py` 772, `core/rate_limits.py` 301, `core/rate_limit_tiers.py` 144, `core/rate_limit_config.py` 67, `rate_limiter.py` 621, `caching_shield/rate_limiter.py` 287, `assistant_gateway/ratelimit.py` 80, `databus/x_intel/x_proxy/ratelimit.py` 44, `domains/billing/x402_exact/ratelimit.py` 72, `domains/poly_attribution/rate_limit.py` 46, `domains/prediction/opportunities/rate_limit.py` 91, `routers/x402_databus_tools/rate_limit.py` 87 · rugbrain: `monitors/social_sentiment/rate_limit.py` 17 |
| retry/backoff | 8 implementations | pry `engine/retry.py` 276 (canonical), `engine/tier_retry_policy.py` 77, plus inline copies in `api/pry_sdk.py:161`, `api/databus_bridge.py:173`, `api/webhook_delivery.py:199`, `intelligence/llm/base_streaming.py:93`, `intelligence/llm/registry.py:73` · rugbrain `ingest_sources/shared/retry.py` 44 |
| dedupe / story key | 18 files / 1,916 lines | rugbrain: `story_key.py` 37, `content_dedupe.py` 99, `ingest_sources/ingest_dedupe.py` 134, `ingest_sources/x_intel/dedupe.py` 135, `app_chunking/_dedup.py` 51, `scam_watch/dedupe.py` 24 · pry: `engine/dedup.py` 129 (SimHash) · rmi: `utils/dedup*.py` 13 files 838, `utils/dedup_addresses.py` 75, `mmr_dedup.py` 347, `feed_quality_pipeline/deduplicator.py` 102, `databus/services/dedup.py` 74 |
| extractor / HTML→text | 17 files | pry: `engine/extractor.py` 179, `engine/extraction.py` 53, `engine/schema_extract.py` 220, `engine/schema_extraction.py` 149, `engine/ocr_extractor.py` 100, `engine/pdf_extractor.py` 146, `engine/email_scraper/extractor.py` 51, `api/routers/scraping/extraction*.py` 495, `intelligence/llm/base_extract.py` 169 · rugbrain: `rss_extract.py` 101, `feature_extractors.py` 316, `pattern_extractor.py` 95 · rmi: `entity_extraction/extractor.py` 136, `domains/scanner/unified/risk_report/_extract.py` 456, `domains/telegram/premium/extract.py` 210 |
| HTTP client / connection policy | 1 real module | pry `commerce/marketplace/http.py` 206 — the only module owning connection policy *and* the only working `Retry-After` parser (`_retry_after_seconds`, line 36) |

## 2. Owners (one per capability)

| Capability | Canonical module | Rule |
|---|---|---|
| retry/backoff + Retry-After | `pryscraper: src/pry/engine/retry.py` + `src/pry/engine/retry_after.py` | pry owns connection policy, so it owns the retry that must respect it. Only implementation with jitter modes, `max_time`, `max_delay` cap and circuit-breaker hooks. |
| HTTP connection policy | `pryscraper: src/pry/commerce/marketplace/http.py` | already the only place that parses `Retry-After`; it must *call* `engine.retry_after` rather than own a second parser. |
| rate limit (inbound / API) | `rmi-backend: app/core/rate_limiter.py` | `UnifiedRateLimiter` is the only copy with Redis + in-memory fallback, tier/category data, hashed identifiers, middleware and dependency; its own docstring says it consolidated 7. |
| rate limit (outbound scraper politeness) | `pryscraper: src/pry/core/ratelimit.py` | token bucket with a Redis fixed-window backend and a documented degrade path; the only limiter that survives multi-replica. |
| dedupe / story identity | `rugbrain: src/rugbrain/story_key.py` | only implementation of *story* identity (sha256 of normalised title + body[:280]); already documents the 4,870-row duplicate bug it fixes. |
| extractor / HTML→text | `pryscraper: src/pry/engine/extractor.py` | extraction is pry's product surface; keeps schema/OCR/PDF siblings under one package. |

Cross-repo note: three separate installs, so no cross-repo *import* exists today. The reference
implementation is pry's; the other repos' canonical modules are pinned by a **parity test**
(`tests/test_retry_parity.py`) against the same delay table, not by a shared package.
`[REVIEW]` the durable fix is a small `fleet-http` package; that is a new repo, not a refactor.

## 3. Differences that matter (measured, not impression)

Retry, same 429 on the wire:

| Copy | attempt cap | base | cap | jitter | honours `Retry-After` |
|---|---|---|---|---|---|
| pry `engine/retry.py` (`RetryConfig`) | `max_retries=3` | `1.0` | `60.0` | `Jitter.FULL` | **no** (needs the new helper) |
| rugbrain `shared/retry.py` (before) | `attempts=3` | `0.5` | none | none | **no** — slept `0.5 * 2**attempt`, worst case 1.5 s total |
| pry `api/pry_sdk.py:161` | `max_retries=2` | inline | `2.0` | none | **no** — `min(0.05 * 2**attempt, 2.0)` → retries a 429 after **50 ms** |
| pry `api/databus_bridge.py:173` | unbounded by config | inline | none | none | **no** — `await asyncio.sleep(2 ** a)` |
| pry `commerce/marketplace/http.py:36` | per caller | — | — | — | **yes** (only one) |

Rate limits, actual numbers:

| Copy | Limit | Backoff / retry signal | Verdict |
|---|---|---|---|
| pry `core/ratelimit.py` | `default_rpm=60`, `burst=100` (memory); Redis fixed 60 s window | memory computes `wait_time` from the token deficit; Redis degraded path hardcodes `retry_after=60` | correct shape; only copy safe across replicas |
| rmi `core/rate_limits.py` | tiers 10 / 60 / 300 rpm, `burst_multiplier` 0.4 / 0.25 / 0.2; categories 5 (`auth`) – 1000 (`health`,`x402`) rpm; `X402_BYPASS_LIMITS = True` | `min(tier_rpm, path_rpm)` composition | most complete; note the x402 bypass |
| rmi `caching_shield/rate_limiter.py` | 15 tokens/s, burst 25 (RPC tiers) | token bucket, in-memory fallback | header says `DEPRECATED` **but `caching_shield/router.py:25` still imports it** — deletion blocked |
| rmi `rate_limiter.py` | per-provider `rpm` 20 / 60 / 99999 | provider dispatcher by remaining capacity | LLM routing, not HTTP limiting — different job, keep, rename |
| rugbrain `monitors/social_sentiment/rate_limit.py` | 1 req/s via module globals (`MIN_REQUEST_GAP`, `_last_request_time`) | `asyncio.sleep` under a shared lock | **wrong**: state lives on the package object, not the limiter — untestable in isolation |

**Named wrong copy:** `pry/api/pry_sdk.py:161` — 50 ms first retry on a 429 with `Retry-After: 60`
is a self-inflicted ban. Second: `rugbrain/ingest_sources/shared/retry.py` — no cap, no jitter,
no header (no importer found by grep `[REVIEW]`, so it may be dead on top of being wrong).

## 4. Consolidation plan (data)

| Capability | Canonical | Callers to migrate | Delete after migration |
|---|---|---|---|
| retry | `pry:engine/retry.py` + `engine/retry_after.py` | `api/pry_sdk.py:149-161`, `api/databus_bridge.py:164-173`, `api/webhook_delivery.py:189-199`, `intelligence/llm/base_streaming.py:93`, `commerce/marketplace/http.py:36`; rugbrain `ingest_sources/*` callers of `shared.retry` | inline backoff blocks above; `commerce/marketplace/http.py::_retry_after_seconds` |
| rate limit (inbound) | `rmi:app/core/rate_limiter.py` | `caching_shield/router.py:25`, `assistant_gateway`, `databus/x_intel/x_proxy`, `domains/billing/x402_exact`, `domains/poly_attribution`, `domains/prediction/opportunities`, `routers/x402_databus_tools`, top-level `app/rate_limiter.py` | `caching_shield/rate_limiter.py`, `rate_limiter.py` (after rename), 4 domain copies |
| rate limit (outbound) | `pry:core/ratelimit.py` | `core/user_ratelimit*.py` should compose it, not re-bucket; rugbrain `social_sentiment` should take a limiter instance | `user_ratelimit_quota.py` if redundant after compose; `social_sentiment/rate_limit.py` |
| dedupe / story key | `rugbrain:story_key.py` (+ `ingest_dedupe` primitives for near-dup) | `rss_store.py:85` (already), `content_dedupe.py`, `x_intel/dedupe.py`, `scam_watch/dedupe.py`, `app_chunking/_dedup.py`; rmi `utils/dedup*.py` (13) + `mmr_dedup.py` + `feed_quality_pipeline/deduplicator.py` + `databus/services/dedup.py` | rmi util cluster, pry `engine/dedup.py` only if SimHash is unused by pages `[REVIEW]` |
| extractor | `pry:engine/extractor.py` | `engine/schema_extract.py`, `engine/schema_extraction.py`, `api/routers/scraping/extraction*`; rugbrain `rss_extract.py` keeps feed cleaning only | `engine/extraction.py` (53 lines, thinnest wrapper) |

Proven in this pass (behaviour parity, not aspiration): `tests/test_retry_parity.py` runs the
**real** rugbrain `get()` against the **real** pry `retry_delay()` on the same response sequence —
identical sleeps with no header (0.5, 1.0), identical and header-honouring with `Retry-After: 2`
(2.0 where the old copy slept 0.5), unparseable header falls back, 200 never sleeps.

## 5. Import guard

`tests/test_utility_import_guard.py` fails if a `rate_limit*` / `ratelimit*` / `retry*` /
`backoff*` / `dedup*` module appears outside a canonical location. Every legacy survivor is an
explicit allowlist entry **with a reason**, and the guard also fails on a *stale* entry, so the
allowlist can only shrink (tech-debt ratchet).
