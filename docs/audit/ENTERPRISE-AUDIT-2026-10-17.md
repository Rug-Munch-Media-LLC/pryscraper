# Pry — Enterprise Audit Register (2026-10-17)

**Scope:** `the pryscraper repo` @ `e5996dbf` plus the live marketing site (`the pry-web repo`).
**Method:** six waves of read-only specialist review (money path, MCP surface, code quality, functional ladder, data domains, tests, brand, docs/DX, DevOps, compliance, pricing, security, API contract, performance, ops, release, DB schema, reconciliation, live site, legality, claims).
**Status:** findings only — no fixes applied by the audit. Every item below was reproduced by reading the tree; items marked **UNVERIFIED** were not.

---

## P0 — block a clean deploy or lose money

| ID | Finding | Evidence |
|---|---|---|
| P0-1 | **Settle ordering.** `verify` persists the payment record and burns the EIP-3009 nonce *before* settlement. A settle failure still yields a usable `payment_id`; the authorization cannot be re-verified. | `payments/x402/handler_verify_record.py`, `self_facilitator/evm_verify.py`, `x402.py` |
| P0-2 | **Any valid DB key bypasses the x402 gate.** `issue_key` defaults `tier="FREE"` with scope `x402`; `enforcement_stages` waves through any authenticated credential without a tier/quota/scope check. Key issuance is loopback-only, so exposure is conditional on a same-host proxy. | `core/api_keys_service.py`, `x402_middleware/credential.py`, `enforcement_stages.py` |
| P0-3 | **`POST /v1/auth/sso` is password replay, not SSO.** Accepts a plaintext password, generates a Playwright script that interpolates it unescaped into JavaScript, returns it. No OIDC/SAML anywhere. | `api/routers/core/auth.py`, `api/auth_connector.py` |
| P0-4 | **Actors bill before validating.** `run_count` and `revenue_usd` increment, then the handler can return `{"success": false, "error": "Missing 'url' input"}`. | `commerce/actor_marketplace.py` |
| P0-5 | **Batch marks paid on failed settlement**, and the tx is already consumed, so retry is impossible twice over. | `payments/x402/batch/payments.py` |
| P0-6 | **26 of 99 MCP tools are dead** — advertised in `tools/list`, return `TOOL_NOT_WIRED`. 99 tools / 49 routes / 24 dispatcher-wired. | `pry_mcp/tool_routes.py`, `fallback_server.py` |
| P0-7 | **Validation failures report success** — executor `{"error": …}` is converted to `isError:false` with the error in the text body. | `pry_mcp/fallback_server.py` |
| P0-8 | **All 3 REST crypto endpoints are 502** — router imports `datasets.crypto_market`; the package is repo-root `crypto_market`. | `api/routers/data/*crypto*` |
| P0-9 | **The ladder cannot classify a block.** `_detect_block_signal(html)` passes a hardcoded 200 and empty headers, so every 403/429 branch is unreachable; a Cloudflare challenge is reported `unavailable`, a timeout `exhausted`. | `engine/tiers_base.py`, `engine/block_detection.py` |
| P0-10 | **Retries are inert and the budget is not what it says.** Tiers `return None`; `async_retry` treats `None` as success. `ScrapeRequest.timeout` (120s) is never read; the chain is capped by `asyncio.timeout(45)`. `use_premium_proxy_first` runs outside that timeout. | `engine/scraper_orchestrate.py`, `engine/tier_retry_policy.py` |
| P0-11 | **Auth trusts the socket peer.** Any peer in `127.0.0.0/8` is authorised in keyless mode; the admin gate returns success for loopback before any key check. Behind a local proxy this authenticates every external request. | `core/middleware_auth.py`, `api/routers/core/admin_router.py` |
| P0-12 | **Migrations are stamped, not run.** `alembic stamp head` runs first and `upgrade head` only if the stamp fails — on an existing DB the stamp always succeeds, so new revisions are recorded as applied without executing. | `docker-entrypoint.sh` |
| P0-13 | **Admin prefix defaults to the non-secret string `pry-admin-dev`** and is baked into the public `openapi.json`. | `api/routers/core/admin_router.py`, `openapi.json` |
| P0-14 | **The release pipeline is disabled** — the entire `release.yml` job is `if: false`. No wheel, sdist, image, tag or publish. `sign-image` is also disabled. | `.forgejo/workflows/release.yml` |
| P0-15 | **x402 ledger writes a column the DB does not have.** `ledger_store` writes `user_id`; migration `0007` never creates it (confirmed: no `user_id` in `0007`, head is `0008`). | `alembic/versions/0007_*`, `payments/x402/ledger_store.py` |
| P0-16 | **Two tables exist only in code** — `hosting_plans`, `hosted_instances` have no migration at all (confirmed: 0 matches in `alembic/`). | `core/db/models_billing.py` |
| P0-17 | **Revenue reporting reads the wrong store and the wrong clock.** Postgres is declared authoritative but analytics read JSONL; records carry `verified_at` (confirmed in `ledger_store`) while the admin path filters on `ts`, so short windows return zero and "recent" returns the oldest rows. | `api/routers/core/admin_shared.py`, `admin_payments.py`, `analytics.py` |
| P0-18 | **Erasure is partial and self-reports complete.** `ERASURE_SCOPE` is exactly `("gdpr/consent", "quality", "sessions")` (confirmed) — no Postgres table, no x402 JSONL, no reports/monitors, yet the request is stamped `completed`. | `compliance/deletion_logic.py`, `compliance/deletion.py` |

## P1 — correctness, cost, trust

- **Money:** batch settlements reach no ledger; `usage` has no `payment_id` (credits-vs-calls unanswerable); verify *and* settle both record usage; `billing-history.total_spent` double-counts packs; `_compute_profits` sums unverified rows; invoices without `settled_at` are re-dated `now` each query; `balance_usd` stored with no recompute; no unique index on `ledger_entries.reference`; no refund path.
- **Schema:** money is `Float` everywhere; `required_amount_atomic` duplicates `amount_usd`; datetimes are naive (`is_paid` catches only `ValueError`); JSON blobs shadow columns with no size cap; 12 unbounded tables and two JSONL files with **zero** retention jobs.
- **Security:** stored XSS in the admin HTML rows; `POST /v1/webhooks/test` has no auth dependency; DNS-rebinding TOCTOU in `safe_get` (the webhook path pins the IP, the scrape path does not); `_validate_host` **fails open** on DNS error (confirmed: `except OSError: … return resolved`); `resources/read` and `prompts/get` are unauthenticated while `tools/call` is not; MCP hot cache keyed on `(tool, args)` only → cross-caller result bleed; no rate limit on the MCP sub-app.
- **Ladder:** `google_cache` is retired upstream and still runs; `archive` returns the oldest capture (no `sort=reverse`); tier health records a win *before* block classification so WAF pages count as successes; gated tiers record losses and are skipped permanently with no decay; `_is_valid` rejects bodies under 500 bytes, escalating valid small JSON through the full chain; `pry.success` is always `false` (status `ok` vs span check `success`).
- **Data:** 12 routers return `{"success": true, "data": []}` on upstream failure; token-security fabricates `risk_score: 50` when GoPlus is down; self-host cannot supply data keys (`env_file: []`, no keys documented).
- **OpenAPI:** `securitySchemes` empty; **0 of 371 operations declare 401/402/429**; 360/371 responses untyped; no examples; `servers` still `localhost:8002`; 8 tags declared vs 84 used; 21 handlers return HTTP 200 with `success:false`; 96 GETs have no pagination; `count` is computed from an already-truncated slice.
- **Release:** version `3.0.0` hand-copied in 10 files while `CHANGELOG` says `3.1.0`; the only tag is `v1.0.0`, unsigned, 841 commits behind; the wheel ships **0 of 111 templates** and ships `test_live.py`/`validate_*.py`; CI runs 3.12 only while claiming 3.11; no checksums or provenance.
- **Ops:** no deploy/rollback/restore/rotate runbooks; production image older than HEAD with a single `latest` tag; the documented deploy path (the documented deploy path) does not exist, so `deploy-all.sh` silently skips Pry; backups exist only in `fleet-infra` with no restore procedure; disk at 83% with no disk alert.

## Verified corrections (claims from earlier passes that are wrong)

| Claim | Status |
|---|---|
| "`pry_scrapes_total` is never incremented" | **Refuted** — incremented in `track_scrape`'s `finally`, used at 5 endpoints. |
| "`/v1/search` docstring advertises a dead route" | **Refuted** — removed; only an explicit disclaimer remains. |
| "Retry policy is not wired" | **Refuted** — `_RETRY_CONFIGS` + `async_retry` are called. The defect is that tiers return `None`, so retries never trigger — a different bug. |
| "Ratchet gates are not in CI" | **Refuted** — all three run in `ci.yml` (`structure-gate`), though `check-monkeypatch.py` exits 0 on failure. |
| "13 payment chains in the enum" | **Refuted** — `SUPPORTED_NETWORKS` has **7** entries (confirmed by import). |
| "`aggregateRating 4.8/24` is in the site source" | **Not reproducible** — zero hits in `pry-web/landing/src`; it was an older live deploy. |
| "`/docs` is 404" | **Refuted** — `docs.pryscraper.com` is Docusaurus 3.10.2 (200); `api/docs` is Swagger (200). Only the apex marketing site is Astro. |
| "HTTP MCP emits `structuredContent`" | **Refuted** — zero occurrences repo-wide; only `outputSchema` differs by transport. |

## Public-claims register (confirmed drift)

| Claim | Where | Truth |
|---|---|---|
| 76 MCP tools | live site (4 source refs + live copy), `registry_manifest.json`, `smithery.yaml` | **99** |
| Scrape $0.005 | site hero + ticker | **$0.001** |
| "from $0.003" | site JSON-LD | cheapest paid op is $0.001 |
| Crawl $0.020 | site ticker | **$0.010** |
| "6 payment chains" | site stats | **7** |
| "MIT" | README badge, several registries | **MIT core + BSL-1.1 stealth** |
| "guaranteed-profit" / "risk-free bets" | `server.json`, registry manifests, docs | arbitrage *candidates*, not guaranteed |
| "first 100 calls free" | site demo | no code path |
| "more MCP tools than any competitor" | README | unsubstantiated |

## Legal / abuse posture

- **No robots enforcement on the primary path**; the only checker fails open and `Crawl-delay` has no consumers.
- Rate limiting is per key only (ENTERPRISE 6000 rpm); no per-target rate or politeness.
- The stealth stack includes **Googlebot UA impersonation**, Tor egress, and **CAPTCHA solving delegated to paid services, on by default**.
- No AUP acceptance, no domain blocklist, no DMCA/abuse contact, no domain kill switch, no per-domain purge, and **no scrape audit trail** (no scraping router calls `audit_event`).

---

## Next 5 — do these, in this order

1. **One migration (`0009`)**: add `user_id` to both x402 ledger tables, create `hosting_plans` + `hosted_instances`, add `UNIQUE(payment_id, tx_hash)`, add `usage.payment_id` and a partial unique index on `ledger_entries.reference`. Back up and run the duplicate pre-check first. *(Unblocks every ledger write and the platform's own accounting.)*
2. **Fix the reporting clock and source**: read `verified_at`/`settled_at` (fall back to `created_at`), serve Postgres when available, count only `verified AND success`, stop dating invoices `now`, and add the `revenue_reconciliation` view with Q1–Q3 running nightly against a drift alert.
3. **Close the auth hole**: replace the socket-peer predicate with trusted-proxy + `X-Forwarded-For` handling that fails closed, refuse to boot in prod on the `pry-admin-dev` prefix, add `Depends(_require_auth)` to `/v1/webhooks/test`, pin the validated IP in `safe_get`, and make DNS failure a 400.
4. **Make erasure true or stop claiming it**: extend `process_deletion` to every Postgres table and the x402 JSONL (delete personal data, pseudonymise financial records with a stated legal basis), derive `completed` vs `partial` from a per-store manifest, add scrape audit events (sampled, 400-day TTL), and only then publish an AUP/takedown promise.
5. **Tell the truth in public**: delete the fabricated testimonials and unprovable superlatives, replace "guaranteed-profit"/"risk-free", generate tool count / prices / chains / licence from `PRY_TOOLS`, `X402_PRICING`, `SUPPORTED_NETWORKS` and the two licence files at build time, and add a blocking `check-claims` gate so the drift cannot return.

*Everything else in the P1 list is real work but not a blocker; the five above are the ones that currently make the product fail on install, misreport its revenue, trust the wrong peer, overstate its compliance, and misprice itself.*

---

### Reproduction commands

```bash
cd the pryscraper repo
rg -n "user_id" alembic/versions/0007_add_x402_ledger_tables.py          # no match
rg -l "hosting_plans|hosted_instances" alembic/                          # no match
./.venv/bin/alembic heads                                                # 0008
rg -n "ERASURE_SCOPE" src/pry/compliance/deletion_logic.py               # 3 JSON roots
rg -n "_DEV_ADMIN_PATH" src/pry/api/routers/core/admin_router.py        # "pry-admin-dev"
rg -n -A2 "except OSError" src/pry/engine/url_guard.py                   # returns resolved (fail-open)
python3 -c "from pry.payments.x402.scheme.networks import SUPPORTED_NETWORKS as n; print(len(n))"  # 7
curl -s https://pryscraper.com/llms.txt | head                            # 76 tools vs 99
```
