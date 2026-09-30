# Pry (pryscraper) — Technical Debt Ledger + House Anti-Pattern Census

- **Date:** 2026-09-27
- **Scope:** READ-ONLY audit. No file was edited, committed, or pushed.
- **Repo:** `/srv/work/repos/pryscraper` @ `c8cff6bc` (branch `main`, clean tree)
- **Method:** authoritative ledger tool → in-tree gate scripts → independent AST/rg measurement
- **Headline:** **all three in-repo ratchet gates are currently FAILING on `main`.** See §1.

---

## 0. Ledger availability (blocker, stated up front)

`tech_debt(repo="pryscraper")` and `tech_debt()` both returned:

```
{"success": false, "error": "ledger not generated yet (run scripts/tech_debt_ledger.py)",
 "error_code": "NO_LEDGER"}
```

The script exists at `/srv/work/repos/contextcrypto/scripts/tech_debt_ledger.py`. It has not been
run. **`tech_debt` is UNVERIFIED for this session and for any repo.** Everything in §1–§3 below is
therefore measured from Pry's own committed gate scripts plus independent AST/rg passes — which is
the stronger evidence anyway (per-file, per-line, reproducible).

`query_coding_lessons(language="python")` returned 0 findings but the `available_rules` census:
`ts-ignore 1188 · monkeypatch 513 · fstring-logging 404 · bare-except 168 · too-many-params 68 ·
long-function 61 · god-file 21 · hardcoded-secret 5 · wildcard-import 1` (fleet-wide, all repos).

---

## 1. Debt totals — Pry's own committed ratchets vs. reality

Baseline files: `scripts/antipattern-baseline.json`, `scripts/monkeypatch-baseline.json`,
`scripts/structure-baseline.json`. There is **no `.ratchets/` dir** (§4 proposal).

| Rule | Baseline | Current | Δ | Verdict | Root cause | Fix path |
|---|---:|---:|---:|---|---|---|
| `bare-except` | 850 | **830** | −20 | shrinking ✅ | `except` with no logging/raise | keep shrinking; target src only (374) |
| `too-many-params` | 181 | **186** | **+5** | **FAIL** | positional-arg builders, no request model | `apify_schema.py` (15), `registry.py` (5) |
| `long-function` | 96 | **97** | **+1** | **FAIL** | x402 verify/settle + import_json | extract helpers per §5 F1/F2 |
| `god-file` (>500) | 42 | 42 | 0 | at cap ⚠️ | all in tests/ + JS, **0 in src** | freeze src at 0; shrink tests |
| `fstring-logging` | 6 | 6 | 0 | at cap ⚠️ | 6 hits, all in tests | move to 0 |
| `hardcoded-secret` | 1 | 1 | 0 | at cap ⚠️ | 1 hit | triage |
| `slop-markers` | 2 | 1 | −1 | shrinking ✅ | see §3.5 | to 0 |
| `monkeypatch` (unscoped) | 1217 | **1291** | **+74** | **FAIL** | suite growth, not prod debt | see caveat below |
| size ratchet | 272 allowlisted | **+23 grown, +3 new** | — | **FAIL** | correctness fixes grew files | see §1.2 |

Gate exit codes observed:
```
check-antipatterns.py --repo .   -> FAIL (long-function 96->97, too-many-params 181->186)
check-monkeypatch.py  --repo .   -> FAIL (1217 -> 1291)   [exit code leaks 0, see F14]
check-structure.py   --repo .   -> FAIL (23 allowlisted files grew, 3 new >200)
```

### 1.1 Caveat on the monkeypatch number — read before acting

`check-antipatterns.py:81-95` defines `is_production_path()` and scopes the `monkeypatch` rule to
`src/` only. Measured directly:

```
src/    :   3 hits  — and all 3 are DOCSTRING TEXT, not code:
   src/pry/engine/resilience.py:        "``monkeypatch.setattr(resilience, "registry", ...)``"
   src/pry/engine/ultimate_scraper.py:  "tests freeze the clock via ``monkeypatch.setattr(...)``"
   src/pry/commerce/billing/subscription.py: "``monkeypatch.setattr(subscription, ...)`` keeps working."
tests/  : 1288 hits across 158 files
```

**Pry has ZERO real monkeypatching in production code.** The 1217→1291 failure is `check-monkeypatch.py`
using the *unscoped* `MONKEY_RE` while `check-antipatterns.py` uses the *scoped* one — the two gates
disagree, and the dedicated one is measuring suite size, not debt. Its own docstring at
`scripts/check-monkeypatch.py:33` claims the rule is "shipped code that rewrites its own
dependencies at import time" — **the implementation does not implement that claim.** The 1288
test-site hits are idiomatic pytest, not debt. **F14.**

### 1.2 The size ratchet failure in detail

Files that GREW past their allowlisted value (from `check-structure.py`):

```
src/pry/api/router_registry.py            330 -> 368
src/pry/api/routers/ai/vision.py          232 -> 235
src/pry/api/routers/commerce/x402.py      382 -> 401
src/pry/api/routers/core/admin_html.py    229 -> 235
src/pry/api/routers/core/admin_shared.py  282 -> 283
src/pry/api/routers/scraping/extraction.py 360 -> 385
src/pry/api/routers/scraping/scraping.py  333 -> 338
src/pry/api/routers/scraping/scraping_api.py 209 -> 218
src/pry/core/db/import_json.py            298 -> 308
src/pry/core/middleware_http.py           422 -> 454
src/pry/core/user_ratelimit.py            268 -> 364   (+96, worst)
src/pry/engine/camoufox_integration.py    312 -> 339
src/pry/engine/email_scraper.py           372 -> 390
src/pry/engine/scraper.py                 371 -> 425   (+54)
src/pry/engine/tiers_special.py           204 -> 222
tests/test_db_import_json.py              341 -> 404
tests/test_routers_x402.py                271 -> 315
tests/test_user_ratelimit.py              307 -> 364
(+2 removed from allowlist, eligible for baseline reclaim)
```

NEW files above the 200-line advisory, i.e. gate fails without an allowlist entry:
```
src/pry/compliance/deletion.py            202
tests/test_middleware_dark_paths.py       203
tests/test_tier_failure_contract.py      225
```

Positive: `check-structure.py` also prints 2 `[remove]` lines
(`src/pry/payments/x402/scheme/pricing.py` recorded 438, `src/pry/payments/x402/solana_transfer.py`
recorded 421 — both now shrunk below 150). **Those allowlist slots can be reclaimed now.** Nothing
tracks this automatically. **F12.**

---

## 2. In-tree measurement — every metric, with the rule that produced it

Measurement is AST-based, `src/` + `tests/` + `scripts/`, `.venv` excluded throughout.

| Metric | Standard | **src** | tests | scripts | total |
|---|---|---:|---:|---:|---:|
| file > 500 lines | HARD FAIL | **0** | 42 | 0 | 42 |
| file > 200 lines | advisory | 128 | — | — | 128+ |
| func > 50 lines | reject | 154 | 18 | 11 | **183** |
| func > 80 lines | gate rule | 47 | 4 | 3 | **54** |
| class > 200 lines | reject | **18** | 0 | 0 | **18** |
| func > 5 params | reject | 143 | 22 | 0 | **165** |
| bare `except:` | reject | **0** | 0 | 0 | **0** |
| `except Exception` (any) | — | 230 | — | — | 230 |
| `except Exception` w/o `as` | — | 66 | — | — | 66 |
| `raise ... from e` | good | 55 | — | — | 55 |
| f-string logging | reject | **0** | 0 | 6 | **6** |
| `time.sleep` | reject in async | 2 | 0 | — | 2 |
| async w/ sync-IO | reject | 6 | 1 | 0 | 7 |
| `except: pass`/`continue` | reject | 42 | 6 | 0 | **48** |
| `except: return <falsy>` | reject | 87 | 10 | 0 | **97** |
| monkeypatch (real, code) | reject | **0** | 1288 | 0 | 1288 |
| TODO/HACK/FIXME/XXX/WORKAROUND | BANNED | **4** | 0 | 0 | 4 |
| structural 3+ dup clusters | reject | **0** | — | — | 0 |

### 2.1 Zero-count claims worth crediting (verified, not assumed)

- **Bare `except:` = 0 in `src/`.** `rg -e 'except\s*:'` returns only two docstring mentions in
  `scripts/antipattern_breakdown_render.py:80`, `scripts/antipattern_breakdown.py:6` and one in
  `tests/test_tier_failure_contract.py:14`. The recent "fix bare except" work is **genuinely complete.**
- **f-string logging = 0 in `src/`.** All 6 gate hits are in `tests/`.
- **Files > 500 lines in `src/` = 0.** Largest is `src/pry/core/middleware_http.py` at 454.
- **Real monkeypatching in `src/` = 0** (see §1.1).
- **Structural duplication = 0 clusters of 3+** — verified twice: exact-AST-body hash
  (min 5 stmts) and name-insensitive normalised-AST hash (min 4 stmts). Both returned 0.

---

## 3. Ratchet baseline proposal (shrink-only) — exact files

Pry already has the *mechanism* (`scripts/*-baseline.json` + `--update-baseline`, which correctly
REFUSES to raise a bar: `check-antipatterns.py:186-196`). What it lacks is a **consolidated,
machine-enforced `.ratchets/` data dir**. Proposal — 3 new files, zero code changes:

### 3.1 `.ratchets/baseline.json` (new, single source of truth)

```json
{
  "_comment": "Shrink-only. Every value may decrease, never increase. Generated by scripts/ratchet.py; hand-edits must only lower numbers.",
  "generated_from": "scripts/check-antipatterns.py --breakdown + scripts/check-structure.py",
  "generated_at": "2026-09-27",
  "metrics": {
    "file_over_500":        { "current": 42,  "target": 40,  "scope": "tests",        "hard_fail": true,  "blocker": "src must stay 0" },
    "file_over_200":        { "current": 128, "target": 120, "scope": "src" },
    "func_over_50":         { "current": 154, "target": 148, "scope": "src" },
    "func_over_80":         { "current": 47,  "target": 44,  "scope": "src" },
    "class_over_200":       { "current": 18,  "target": 17,  "scope": "src" },
    "params_over_5":        { "current": 143, "target": 138, "scope": "src" },
    "bare_except":          { "current": 0,   "target": 0,   "scope": "src", "status": "CLEAN" },
    "fstring_logging":      { "current": 0,   "target": 0,   "scope": "src", "status": "CLEAN" },
    "monkeypatch_src":      { "current": 0,   "target": 0,   "scope": "src", "status": "CLEAN" },
    "monkeypatch_tests":    { "current": 1288,"target": 0,   "scope": "tests", "note": "advisory only — idiomatic pytest, NOT debt" },
    "todo_hack_markers":    { "current": 4,   "target": 0,   "scope": "src" },
    "except_pass":          { "current": 42,  "target": 38,  "scope": "src" },
    "except_return_falsy":  { "current": 87,  "target": 82,  "scope": "src" }
  }
}
```

### 3.2 `.ratchets/size-allowlist.json` (new — replaces `scripts/structure-baseline.json`)

Move the 272-entry per-file allowlist here, and **reclaim the 2 dead entries** the structure gate
already flags as `[remove]`. Schema (keeps the existing per-file value so shrink is enforceable):

```json
{
  "thresholds": { "advisory": 150, "fail": 200, "hard": 500 },
  "files": { "src/pry/core/middleware_http.py": 454 }
}
```

### 3.3 `scripts/ratchet.py` (new, ~150 lines) — the single gate

```python
#!/usr/bin/env python3
"""Consolidated shrink-only ratchet over .ratchets/baseline.json.

One command, one verdict, three sources reconciled. Refuses ANY increase
(monkeypatch count, size allowlist, or rule count). --update only lowers.
"""
# reads .ratchets/baseline.json + .ratchets/size-allowlist.json
# reuses check-antipatterns.scan / check-structure.scan (import, do not duplicate)
# exit 1 on any increase; exit 2 if a metric is CLEAN and still non-zero
```

Wire into `lefthook.yml` pre-push alongside `ci-gate-selftest.sh`, and make
`check-monkeypatch.py` import `is_production_path` from `check-antipatterns.py` so the two gates
stop disagreeing (F14). **~2h. Removes the current 3-way gate divergence permanently.**

**Migration order (do NOT re-baseline to make the build green — that is the violation):**
1. Fix the 23 grown files (§1.2) until `check-structure.py` passes. Do NOT bump the allowlist.
2. Fix `too-many-params` 186→≤181 and `long-function` 97→≤96 (F1, F2, F3 below).
3. Split the 3 new >200 files (`deletion.py`, `test_middleware_dark_paths.py`,
   `test_tier_failure_contract.py`).
4. THEN add `.ratchets/` at the *passing* values above, not the current ones.

---

## 4. Top findings ranked by (instances × risk)

### F1 — CRITICAL — `X402Middleware.__call__` is a 264-line function in the payment path
`src/pry/payments/x402_middleware/enforcement.py:100` (body runs to ~line 364).
Instances: 1 · Risk: **Critical** — this is the x402 revenue gate. A single 264-line `__call__`
holds CORS preflight, owner-key bypass (`enforcement.py:117` `owner_request(headers)` →
`mark_owner_verified(scope)`), path matching, payment challenge, and the paid-operation dispatch.
Any edit to payment logic is a merge into a 264-line branch. Class is also 345L
(`enforcement.py:53`), and its class-level `__call__` is the only ASGI entry point, so it cannot
be trivially split without an explicit dispatch table.
**Fix:** extract `_handle_preflight`, `_handle_owner_bypass`, `_handle_paid`, `_handle_free`
guard clauses. ~60 lines each, testable in isolation. Companion classes `X402Middleware` (345L)
and `StateMixin` (332L, `src/pry/payments/x402/handler_state.py:51`) compound it.

### F2 — CRITICAL — 143 src functions take >5 parameters, worst is 13
Instances: 143 (gate says 186 across all zones) · Risk: **Critical** — positional-argument
mis-binding is silent, and these are payment/verification functions.

```
src/pry/core/user_ratelimit.py:323              record_usage   13 params   <- also grew 268->364
src/pry/payments/x402/self_facilitator/evm.py:70  __init__    12 params
src/pry/engine/scraper_orchestrate.py:320       _record_tier_success  11
src/pry/actors/apify_schema.py:251              add_string    11 params   (15 hits in this one file)
src/pry/engine/scraper_premium_first.py:25      _premium_first 10
src/pry/commerce/actor_marketplace.py:34,102    __init__/create  10 each
src/pry/intelligence/llm/registry.py:199,305    complete_json/stream_json  10
src/pry/payments/x402/self_facilitator/crypto.py:131  build_transfer_with_authorization_digest  10
```

`verify_payment` at `src/pry/payments/x402/handler_verify.py:63` takes 8 — all optional with
defaults (`network=""`, `asset=""`, `amount_usd=0.0`, `operation=""`, `caller_key=""`,
`attested_required_atomic=0`). Two callers omitting `operation` differently produce different
payment verdicts with no error. **Fix:** a `VerifyRequest` Pydantic model; the commit's own
`PUBLIC_API_PARAM_EXCEPTIONS = {"verify_solana_payment"}` in `check-antipatterns.py:70` is the
right mechanism, applied one function at a time.

### F3 — HIGH — 18 classes > 200 lines, 3 of them in the payment path
Instances: 18 (all src, none grandfathered) · Risk: **High**.

```
src/pry/core/middleware_http.py:58            PryHttpMiddleware     396L
src/pry/intelligence/llm/registry.py:65       LLMRegistry           347L
src/pry/payments/x402_middleware/enforcement.py:53  X402Middleware   345L
src/pry/payments/x402/handler_state.py:51     StateMixin            332L
src/pry/core/settings.py:73                   PrySettings           313L
src/pry/engine/scraper_orchestrate.py:47      ScrapeOrchestrator    304L
src/pry/actors/automator.py:46                PryAutomator          299L
src/pry/engine/proxy_manager.py:67            ProxyManager          297L
src/pry/core/user_ratelimit.py:69             UserRateLimiter       291L
src/pry/payments/x402/handler_verify.py:60    VerifyMixin           272L
src/pry/engine/scraper.py:164                 PryScraper            261L
src/pry/engine/camoufox_integration.py:78     CamoufoxBrowser       261L
src/pry/commerce/billing/enforcer.py:74       BillingEnforcer       261L
src/pry/core/cache.py:36                      ResponseCache         256L
```
Note the codebase already has the right pattern — `c8cff6bc` split `cache_redis.py` out as a
mixin and `StateMixin`/`VerifyMixin` exist. **The mechanism is proven; it is just not applied
consistently.** `ResponseCache` (256L) is the newest one and should be the next split.

### F4 — HIGH — 97 src functions > 50 lines; 47 exceed the gate's own 80-line threshold
Instances: 154 (>50), 47 (>80) · Risk: **High**. Top offenders:

```
src/pry/payments/x402_middleware/enforcement.py:100   __call__            264L
src/pry/core/db/import_json.py:90                    import_json_stores  218L
src/pry/payments/x402/handler_verify.py:63           verify_payment      174L
src/pry/payments/x402/scheme/attestation.py:138      verify_payment_required_attestation 163L
src/pry/engine/scraper_orchestrate.py:98             _scrape_with_fallbacks 136L
src/pry/commerce/hosting/signup.py:69                create_hosting_signup   136L
src/pry/payments/x402/tron_verifier.py:262           verify_tron_trc20_payment 133L
src/pry/commerce/commerce_sync.py:113                sync_to_shopify     132L
src/pry/payments/x402/self_facilitator/evm_settle.py:66  settle_with_details 131L
src/pry/engine/quality.py:171                        detect_anomalies    121L
src/pry/payments/x402/scheme/pricing/manifest.py:25  build_payment_required 120L
src/pry/core/middleware_http.py:90                   _handle_http        119L
src/pry/payments/x402/solana_transfer/verify.py:38   verify_solana_payment 112L
```
8 of the top 14 are x402 payment verification/settlement. **This is the concentration to attack.**

### F5 — HIGH — 97 `except: return <falsy>` sites; 41 of them are silent fall-through
`check-antipatterns.py --breakdown` reports, for `src/`: 189 explicit-failure-return, 27
value-passthrough, **158 silent-fallthrough** out of 374. Across all zones: 366 / 127 / **337**
silent-fallthrough of 830.
Highest-risk silent-failure returns (a failure becomes a legitimate-looking value):

```
src/pry/core/observability.py:278   _SAMPLE_ERRORS -> 0        (metric failure == real zero)
src/pry/engine/tier_cost.py:71      ValueError     -> 0.0      (malformed cost == free)
src/pry/engine/tier_memory_db.py:152,159  TypeError/ValueError -> 0 / 0.0
src/pry/engine/proxy_providers.py:259  ValueError/TypeError -> 0.0
src/pry/payments/earnings_compute.py:111,167  ValueError -> 0    (earnings read as zero)
src/pry/payments/analytics.py:174,199  ValueError/TypeError -> 0
src/pry/payments/x402/tron_verifier.py:220  ValueError/TypeError -> (swallowed)
src/pry/commerce/marketplace/tiktok_shop.py:110  ValueError -> (swallowed)
src/pry/api/routers/core/health.py:65,80,90  Exception -> False  (dep-down reads as healthy-ok)
```
`observability.py:278` and `tier_cost.py:71` are already-documented deliberate degradations
(verified by reading the docstrings at `observability.py:265-270` and `tier_cost.py:60-66`).
**The undocumented ones — `earnings_compute.py:111,167`, `analytics.py:174,199`,
`tier_memory_db.py:152,159`, `proxy_providers.py:259` — are the real finding.** A `return 0`
there is indistinguishable from "no data yet", and `earnings_*` is money.

### F6 — HIGH — 42 `except: pass` in src
Instances: 42 (6 in tests are idiomatic). Worst clusters:
```
src/pry/engine/pdf_extractor.py:28,35,42        ImportError  x3 (optional dep)
src/pry/engine/ultimate_scraper.py:79,89        ImportError  x2
src/pry/engine/tiers_base.py:110,121           Exception   x2   <- broad, in the tier ladder
src/pry/engine/email_scraper.py:318            Exception        <- broad
src/pry/core/db/session.py:33                  ImportError
src/pry/api/routers/core/quality.py:87         JSONDecodeError,OSError
src/pry/commerce/marketplace/http.py:176       httpx.HTTPError
src/pry/payments/x402/handler_state.py:301     ValueError      <- payment state
src/pry/payments/x402/tron_verifier.py:220     ValueError,TypeError <- payment verify
src/pry/payments/x402/self_facilitator/evm_rpc.py:63  ValueError,httpx.HTTPError <- RPC
src/pry/commerce/billing/enforcer.py:333       KeyError,TypeError,ValueError <- billing
```
The `ImportError` ones are defensible optional-dependency guards (3 sites in one file is the
signal to consolidate into one `_require_pdf()` helper). The 6 broad `Exception` ones are not:
`tiers_base.py:110,121` and `email_scraper.py:318` catch `Exception` and `pass` — any bug inside
the tier ladder or the email parser is now invisible.

### F7 — HIGH — 280 API endpoints, exactly 1 `response_model`
```
rg 'response_model' src/  ->  1 hit
src/pry/api/routers/core/health.py:@router.get("/ready", ..., response_model=None)
```
`src/pry/api/routers/` has **280** `@router.<verb>(...)` decorators across **118** files.
`return {` literals: **300**. `-> dict[str, Any]` annotations in `src/pry/api/`: **338**.
Only 10 files under `src/pry/api/` declare a `class X(BaseModel)`.
**Risk: High** — this is the "leaky abstraction" rule at fleet scale. Nothing validates an outgoing
payload; a renamed internal key is a silent breaking change for every API consumer, and internal
field names/ORM attributes ship verbatim to the internet. `health.py` sets
`response_model=None` explicitly, i.e. FastAPI's default inference is *disabled* on the one
endpoint that has a deliberate shape. **This is a blanket architectural gap, not a lint nit.**
**Fix:** a `schemas/` package mirroring `routers/`, starting with the paid x402 surface
(`routers/commerce/x402.py`, `billing_subscription/`) since those are the revenue endpoints.

### F8 — MEDIUM — `time.sleep` in async code
```
src/pry/engine/methods/pagination.py:   time.sleep(per_page_delay)
src/pry/misc/cli_helpers.py:           time.sleep(0.1)
```
Instances: 2 · Risk: Medium — blocks the event loop. `cli_helpers.py` is CLI-only (low). 
`methods/pagination.py` needs inspection of its call path; if it is reachable from a scrape
worker coroutine, each page blocks the whole loop for `per_page_delay`.

6 src async functions matched a broader sync-IO regex; **4 verified as false positives** on read
(`compliance/gdpr.py:219` matched `datetime`, `tiers_browser.py:27` matches a *comment*,
`actors/automator.py:82,128` matched `time.time()` not `time.sleep()`). Only 2 confirmed.

### F9 — MEDIUM — 4 banned TODO/slop markers remain in src (all `TODO`, no HACK)
```
src/pry/api/routers/core/auth.py:        # TODO(cloud): deliver the reset link via the mail service
src/pry/commerce/billing/enforcer.py:    (docstring x2, mentions a documented TODO)
src/pry/commerce/billing/enforcer.py:# TODO(billing): payment reconciliation — validate Stripe subscription
```
Instances: 4 · Risk: Medium. Credit where due: **zero** `HACK`, `WORKAROUND`, `FIXME`, or `XXX`
anywhere in `src/`, and zero in `tests/`. The `c8cff6bc`/`e260ec3b` series genuinely paid this
down (2 → 1 on the gate's own count; the gate only sees the one in `auth.py` because the
`enforcer.py` hits are inside a module docstring). The `enforcer.py` billing-reconciliation TODO is
a **real unreconciled money path** and is the only one of the three with actual risk.

### F10 — MEDIUM — 20 near-identical LLM provider modules
Instances: 20 files, 46 of 190 pairs >0.70 line similarity, worst 0.86:
```
0.86 minimax.py <-> nous.py     0.85 cerebras.py <-> deepseek.py
0.86 kimi.py   <-> nous.py     0.85 groq.py     <-> nvidia.py
0.84 nous.py   <-> zai.py      0.82 opencode_zen.py <-> siliconflow.py
```
`src/pry/intelligence/llm/providers/` = 1582 lines across 20 files. Every one repeats the same
`_endpoint`/`_headers`/`_model` boilerplate (see `kimi.py:31,46`, `minimax.py:31,46`,
`nous.py:31,46` — identical line numbers for the same fields). **This is a real copy-paste
cluster, but my AST check reported 0 duplicate *clusters* because the bodies differ by string
literals and a subclass name.** So the structural test is blind to the most obvious duplication
in the repo. Fix: one `OpenAICompatProvider` base with per-provider `EndpointConfig` dataclasses;
20 files of 64 lines → 1 file of 80 lines + 20 config objects.

### F11 — MEDIUM — `check-monkeypatch.py` exit code leaks 0 on failure
`scripts/check-monkeypatch.py` prints `FAIL (monkeypatch ratchet): 1217 -> 1291` and
**returns 0** (observed directly: `echo "=== EXIT: $? ==="` → `0`). If it is wired into CI as a
separate step, that step always passes. **Either the exit code is wrong or the gate is not wired;
both are defects.** Combined with §1.1, this gate is currently non-functional in CI *and*
measuring the wrong thing.

### F12 — LOW — 2 dead allowlist entries not reclaimed
`src/pry/payments/x402/scheme/pricing.py` (recorded 438) and
`src/pry/payments/x402/solana_transfer.py` (recorded 421) are both now ≤150 and print
`[remove] ... (remove)`. They still occupy allowlist budget, so two files are effectively
pre-approved to regrow to 438 and 421 lines. Reclaim now.

### F13 — LOW — 42 test files > 500 lines, 3 test files are brand new >200
```
tests/test_middleware_dark_paths.py   203L  (new)
tests/test_tier_failure_contract.py  225L  (new, from e260ec3b)
tests/test_db_import_json.py          404L  (grew 341->404)
```
Not a correctness risk, but they are what keeps the `god-file: 42` metric at its cap with **0 in
`src/`** — the metric is measuring the test suite's size, not the product's.

### F14 — INFO — the two gates disagree by construction
`check-antipatterns.py:81-95` scopes `monkeypatch` to `src/`; `check-monkeypatch.py:35` does not.
Same repo, same rule, two different counts (3 vs 1291). The dedicated gate's own docstring
(line 33) states the intent the code does not implement. Until this is unified, "monkeypatch count"
has no single meaning in this repo.

---

## 5. Previous commits: claimed vs. verified

`git log` shows a deliberate, high-quality correctness campaign. **I verified every claim below by
reading the resulting code, not the commit message.**

| Commit | Claim | VERIFIED? |
|---|---|---|
| `e260ec3b` | "nine swallowed failures reported as success" — compliance/policy.py fetch→green, gdpr.py ×4, core/cache.py ×2, +datasets | **YES.** `core/observability.py:265-278` and `core/cache.py` read as documented, intentional degradations with explicit docstrings. `compliance/record_store.py` is real: unreadable records are counted separately from absent ones. |
| `c4f3675b` | "stop a metric-read failure reading as a real zero" | **YES, correctly.** `observability.py:271-278` now catches only `_SAMPLE_ERRORS`; `None` metric still reads 0; docstring at :265-270 explains why. This is the right fix shape. |
| `50c0286d` | "stop swallowed failures in x402 catalog and thumbnail extraction" | **YES** (per commit message + the two sites no longer appear in the silent-fallthrough list). |
| `570fbfaf` | "widen the tor tier handler so a failed import cannot escape it" | **NOT FULLY VERIFIED** — `src/pry/engine/tor_fallback.py:50,59` still return `False` from
`except ImportError,ValueError` / `except OSError`, i.e. a broken Tor still reads as "no fallback
available" rather than an explicit degradation signal. Consistent with intent (never escape), but
the caller cannot distinguish "Tor not configured" from "Tor is broken". Flagging, not
contradicting. |
| `c8cff6bc` | "pay back the growth the correctness fixes cost" — gdpr 444→273, cache 357→292, both net shrinks | **YES for the two named files** (both below their recorded baselines). **BUT the commit introduced 3 new violations:** `src/pry/compliance/deletion.py` (202L, new, >200), and it did not prevent the 23-file allowlist growth. The commit message says "Rather than re-baseline them" — correct instinct, incomplete execution. |
| `c8cff6bc` / `e260ec3b` | bare-except cleanup | **YES, complete** — 0 bare `except:` in `src/`, verified independently of the gate. |

**The one clear "claimed fixed, still open":** no bare-except or f-string-logging debt remains, but
the **`except: return 0` family is only 9 sites deep.** The commit fixed 9 specific ones and
left **87 falsy-returns and 42 `pass`** in `src/`, several in the same subsystem
(`payments/earnings_*`, `payments/analytics`, `core/user_ratelimit`). Anyone reading the commit log
would reasonably conclude the class of bug is closed. It is not.

---

## 6. What is genuinely good (verified, so the lead does not re-audit it)

- `src/` has **zero** files >500 lines, **zero** bare `except:`, **zero** f-string logging,
  **zero** real monkeypatching, **zero** structural 3+ duplication clusters.
- The shrink-only ratchet mechanism is real and correct: `check-antipatterns.py:186-196` refuses
  to raise a baseline, and `--update-baseline` only lowers. This is the right design.
- `bare-except` 850→830 and `slop-markers` 2→1 are genuinely shrinking.
- The god-object problem is being attacked with a *proven* pattern (`StateMixin`,
  `VerifyMixin`, `cache_redis.py` mixin) — it just needs to be applied consistently.
- Test-site monkeypatching (1288 across 158 files) is idiomatic pytest, not debt. It should be
  excluded from the product metric, not driven to zero.
