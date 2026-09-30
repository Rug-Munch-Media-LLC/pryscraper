# Pry — 50 Next-and-Needed to Enterprise Quality
**Date:** 2026-09-27 · **Subject:** `/srv/work/repos/pryscraper` @ `c8cff6bc` · **Method:** 7 parallel specialist audits + lead-side independent verification

**Grade: B-.** The code is unusually disciplined on the *loud* metrics and the *system* is ungoverned. `bare except` / f-string logging / `monkeypatch` in `src/` are genuinely **0**. But gates exist and are **red or not blocking**, money and admin paths are **untested**, one **SSRF class is live**, one **live GDPR Art. 17 defect** is in the compliance code, and the crawler has **no per-source freshness signal** — the single failure mode that makes a crawler silently useless.

---

## Verification ledger (what I checked myself)

Subagents disagreed on 3 load-bearing facts. I resolved each against the tree:

| Claim | Verdict | How |
|---|---|---|
| "One CI workflow" (my own first recon) | **WRONG** | `.forgejo/workflows/` = **7 workflows, `ci.yml` 1068 lines / 30 jobs** is canonical. `.github/workflows/ci.yml` (164 ln) is a **stale mirror with no GitHub remote** |
| "No ratchets exist" (my own first recon) | **MISLEADING** | No `.ratchets/` dir, but `scripts/{structure,monkeypatch,antipattern}-baseline.json` exist and are gated at `ci.yml:1047-1068`. **All 3 currently FAIL on main** |
| `mypy ... *.py` typechecks the repo | **FALSE** | `ci.yml:44` + **0 root-level `.py`** → glob unmatched → **0 of 512 files type-checked** |
| `extraction.py` fetches user URL with no guard | **CONFIRMED** | 6× `client.get(url)` @ 40,64,101,149,185,204; **zero** `url_guard` in file |
| GDPR erasure scans prod data dir | **CONFIRMED** | `deletion.py:138` hardcodes `~/.pry/quality`; prod is `PRY_DATA_DIR=/var/lib/pry` |
| 3 different coverage floors | **CONFIRMED** | `--cov-fail-under=73` (forgejo) vs `55` (github mirror) vs `45` (codecov.yml comment, exists nowhere) |
| `x402` replay untested @ `handler_state.py:230-239` | **MIS-DESCRIBED** | 230-239 is the *startup `_load_settlements` recovery* path, not the replay check. Coverage gap may be real, line refs are wrong → **re-verify before acting** |

---

## WAVE 0 — Critical: live defects (do first, all S/M effort)

1. **SSRF: guard the 6 unguarded extraction routes.** `extraction.py:40,64,101,149,185,204` call `client.get(url)` on request input. `url_guard` exists, passed a 12/12 bypass battery, and is **never imported here**. Routes are free in the x402 map ⇒ **IMDS `169.254.169.254` reachable**. Fix: import + call `url_guard` at all 6.
2. **Fix the GDPR erasure path scope.** `deletion.py:138,158` (and `gdpr.py:193,201`) hardcode `~/.pry/…`; prod data lives in `PRY_DATA_DIR`. On prod it returns `{"success": true, "deleted_records": 0}` and stamps the request `completed` — a live Art. 17 defect. Import `PRY_DATA_DIR`; **return failure when `deleted_records == 0`**.
3. **SSRF on `ai/analysis.py`** — `:132` fetch + `:187-196` POST to attacker-supplied `webhook`. Pry's own better DNS-pinning validator at `webhook_delivery.py:32-70` is never called here.
4. **SSRF via redirect: `parsing.py:113`** uses `follow_redirects=True`, which bypasses the guarded scrape fallback directly above it.
5. **Path traversal: `sessions.py:25-27`** — `SESSIONS_DIR / f"{session_id}.json"` with `session_id` from the request body, reachable from **3 free routes**.
6. **Transposed args in `handler_verify.py:296-320`** — `authorize_payment` passes `operation`/`caller_key` in the wrong slots. Zero callers today, so unexploitable; a live money-path bug the day someone wires it.
7. **Add a semgrep SSRF rule to CI.** The guard is strong; its callers keep going missing. Without the rule, #1 recurs.
8. **Make Trivy blocking.** Both steps are `continue-on-error: true` (`ci.yml:502,507`) ⇒ **HIGH CVEs ship green**. `sign-image` is `if: false` (`:692`) ⇒ **nothing is ever signed**.

---

## WAVE 1 — Gate enforcement: make the gates real (the 12 RED gates)

9. **Add ONE aggregate `gate` job** to `ci.yml` with `needs:` across all 30 jobs, a `timeout-minutes`, and mark it the required check. *Root cause of every other RED gate* — without it, every gate shipped from here on is unrequired by default. 30 minutes.
10. **Delete or quarantine `.github/workflows/ci.yml`.** No GitHub remote exists; it carries a `mypy *.py` glob that typechecks 0 files and a `--cov-fail-under=55` that contradicts canonical 73. A wrong-but-readable CI file is a trap.
11. **Fix `[tool.coverage.run] source`.** 17 of its entries are bare module names that do not exist (all 512 files are under `src/pry/`), plus `"routers/"` with an invalid trailing slash. The **local** coverage gate is a no-op; CI only works because it uses `--cov=.`.
12. **Reconcile the 3 coverage floors** to one number sourced from one place. `codecov.yml` documents 45, which exists nowhere.
13. **Wire `lint-imports` into CI.** `.importlinter` has **4 contracts and all 4 pass today** — and nothing runs them. `ci.yml:154-164` is triple-non-blocking (`||echo`, `||true`). *Highest-leverage single fix after #9:* everything else becomes regression-locked for free.
14. **Delete the stale `[REVIEW]` "dormant" note** on importlinter contract 3, in the same change that wires #13 — otherwise the next agent reads it as a permanent exemption.
15. **Extend importlinter contracts** to the inversions currently uncovered: `pry.core → pry.engine|pry.actors`, `pry.{engine,commerce,payments,actors} → pry.misc`, plus a forbidden-cycle contract.
16. **Fix the mutation baseline.** `BASELINE = 60.0` at `ci.yml:854` is a hardcoded literal and is documented as raiseable — not shrink-only. 392 no-test mutants are untracked.
17. **Make the fuzz job real** — `continue-on-error: true` means it can never fail.
18. **Turn on `xfail_strict` + pin `pytest-randomly` seed.** Currently neither exists ⇒ order-dependent tests and silent xfails.
19. **Add the missing gates** (absent, in value order): `semgrep` w/ ai-guardrails, `bandit`, `gitleaks` full-history in CI (staged-only pre-commit is not a history scan), `pip-audit`/`safety`, `shellcheck` over `scripts/`, `actionlint`, `hadolint` × 2 Dockerfiles, `zizmor` (Actions hardening), `syft` SBOM + `cosign` sign, Renovate dry-run, OpenAPI drift test, CLI e2e lane.
20. **Confirm Forgejo branch protection actually requires the new `gate` job.** The CI audit could not read Forgejo's required-checks config — so #9 may still be non-binding. Verify before declaring victory.
21. **Build the fleet `tech_debt` ledger.** `tech_debt(repo="pryscraper")` returns **`NO_LEDGER`** fleet-wide (2 independent agents hit it). The "authoritative" number does not exist, so every debt claim is unbenchmarked.

---

## WAVE 2 — Money & admin paths: tests that have teeth

22. **Test x402 replay rejection + fail-closed branches.** *(Re-verify the line refs first — see ledger #7.)* Aggregate payments coverage reads 83.6% while the two lines that reject a duplicate `tx_hash` are unexecuted. Silent pass = free money.
23. **`auth_connector.py` isolation test.** Module is at **39.7%** with 34 missing branches, and `rg "authz" tests` returns **0 files**. Auth is the gate on every paid route.
24. **Fix the live-credential-store test.** `tests/test_auth_connector.py:22-33` writes to the **global** credential store with no `tmp_path`.
25. **Add the full migration-chain test.** Only **one** `command.downgrade` call exists in 7,021 tests (`test_db_migrations.py:64`, rev 0008 only). `b3b4faf8e50d` has `upgrade=1, downgrade=0` ⇒ **billing schema is unrollbackable**.
26. **De-monkeypatch the test suite.** 1,228 `monkeypatch.setattr` + 523 `patch(` across **172 of 301** test files, against **1** DI-seam call site. Our corpus known-good is DI seams (VALUES/SERVICES bind + override/apply/restore), not module-attribute patching.
27. **Kill the 955 tautological asserts** (`assert True`, `assert x is not None`, `assert len(x) >= 0`) and the **0-byte** `tests/test_observability_spans.py`.
28. **Delete the dead `test.sh`** — it `cd /path/to/pry` and imports a module that no longer exists.
29. **Add `test_tier_retry_policy.py`** — the file is absent from the coverage DB, so no test has ever imported it.
30. **Add `test_openapi_contract.py`.** `openapi.json` ships with no drift test, and a stray `pact-mock-service.log` sits at repo root.

---

## WAVE 3 — Data layer & crawler-specific integrity

31. **Per-source freshness metric.** `pry_scrapes_total` (`observability.py:63`) has **no `source` label** ⇒ 61 dead sources look identical to 1 healthy one. The working `get_staleness_dashboard()` is never scheduled or exported. *The #1 operational failure mode for this product class* — a crawler that stopped fetching is indistinguishable from one with no new data.
32. **Schedule and export the staleness dashboard**, then alert on it.
33. **Fix the false idempotency in `import_json.py:95`** — it *claims* idempotency it does not implement: 13 bare `session.add` into `unique=True` tables and **zero `ON CONFLICT` anywhere in `src/`**. A re-run rolls back the whole batch while `counts` reports success.
34. **Make the scraper read the site catalog it already validates.** `site_catalog/` is a genuinely good contract (62 entries, `SiteCatalog` raises on bad data) that the scraper **never reads** — and only **5 of 62** are `tested: true`.
35. **Wire the orphaned migration gate.** `check_migrations.py` exists and is called from nothing. (Migrations themselves are clean: linear, single head `0008`, zero data-mutating ops.)
36. **Introduce Pydantic at the engine boundary.** **Zero** `BaseModel` in the engine; **1 of 280** endpoints declares `response_model`.
37. **Fix the 22 blocking sync-SQL call sites in `async def`.**
38. **Enforce robots.txt.** Honored on **1 of 62** hosts while the catalog's `robots` field is decorative.

---

## WAVE 4 — Structure

39. **Extract the composition root.** `core/deps.py:15-24` imports `engine`+`actors` — `core` is a composition root, not a layer. Move to `pry/composition_root.py`; removes 5 upward edges.
40. **Retire `pry/misc/`.** 10 files / 1,523 lines mixing CLI + `training_data` + `signup_automation` + `x402` + config IO, and it is the **most-imported shallow module in the tree** (18 inbound edges from 4 packages). Split into `pry/cli/`, `pry/config_files/`, `pry/intelligence/`; delete the rest.
41. **Delete the dead `src/payments/` directory.** Untracked, one `.pyc`, unpackaged, zero importers, stale since `86d21b98`. It sends reviewers hunting a "duplication" that cannot exist.
42. **Fix the packaging.** 27 of 28 `include` patterns in `pyproject.toml:177-205` are dead. `datasets/` (283 py), `actor_factory/` (137), `pry_mcp/` (70), `crypto_market/` (17) are all **unshipped**; `src/main.py:14-17` sys.path-hacks `actor_factory`. `pip install pryscraper-mcp` ships `pry` only.
43. **Re-home `pry.api.client`** → `pry/core/http_client.py` (where the impl already lives). 46 importers reaching into the transport layer; `intelligence` alone has 19.
44. **Halve the 562 function-local imports.** These **are** the dependency-inversion mechanism for 15 SCCs / 62 modules (`pry.commerce.billing` × 11). Hoisting any one deferral = ImportError. Undocumented, unenforced ⇒ ratchet to zero-growth.
45. **Fold 64 `APIRouter`s into 3 aggregate routers per subsystem** (core/=28, data/=25, commerce/=20, scraping/=14, integrations/=9). Also fold the stray `pry/payments/crypto/router.py` (a router outside `api/`).
46. **Split the 128 files >200 lines** and 18 classes >200 (worst: `core/middleware_http.py` 454, `intelligence/llm/registry.py` 432, `actors/apify_schema.py` 429). `fleet-gates.scan-roots` is already at `pyproject.toml:531`.
47. **Break up `X402Middleware.__call__` (264 lines) — it is in the payment path.** Split the 47 functions >80 lines and the 143 src functions >5 params (worst 13 at `user_ratelimit.py:323`).
48. **Close the swallowed-failure class.** Bare `except: pass` = **42** in src, `except: return <falsy>` = **97** — including money paths at `earnings_compute.py:111,167`. The "nine swallowed failures fixed" claim is only 9 deep.
49. **Fix the 23 grown ratchet-allowlist files, never re-baseline.** All 3 gates are red today: long-function 96→97, too-many-params 181→186, monkeypatch 1217→1291 (and `check-monkeypatch.py` **exits 0 on failure** — a broken gate). Create the standard `.ratchets/` dir with shrink-only `baseline.json` + `size-allowlist.json`, widen `scan-roots` to cover `routers/`, `pry_mcp/`, `compliance/`, and reconcile the 216-byte `antipattern-baseline.json` against 19 real `BLE001` suppressions.

---

## WAVE 5 — Niche parity (peers: Scrapy, Crawl4AI, Firecrawl, Apify, Crawlee, browser-use)

50. **Ship resumable jobs.** `rg 'resume_state|checkpoint|resumable' src/pry/` → **0 hits**. Crawl4AI ships `resume_state`; Firecrawl ships async job + status polling. Long crawls die at the process boundary — and Pry has no answer.

### Where Pry already beats every peer (do not regress these)
- **x402 micropayments** — 7 EVM + SOL + TRON, self-hosted facilitator, EIP-7702, **no account, no card, machine-payable**. No peer has this. But: it's a *rail*, not a product (no dashboard/invoices/seats/tax) — Crawl4AI's commercial ladder still beats it for human buyers. Pry correctly runs **both** lanes; keep both.
- **112–113 MCP tools + 6 registry manifests + no-account discovery.** Score 5/5.
- **Per-tool annotation audit trail** — `pry_mcp/tools/annotations.py:22-30` records a date and reason per tool. Nothing else in the niche does this.
- **Blocking mutation gate + shrink-only ratchets + gate self-test.** No peer found doing this.
- **Validated declarative site catalog** (62 entries, raises on bad data) and a **15-tier cost-aware adaptive chain** with per-domain memory.

### Scorecard (lead's read of the audit)
Type safety **2** · Extensibility **4** · Async **3** · Output contract **3** · Failure semantics **4** · Observability **3** · Quality gating **4** · Packaging/DX **3** · MCP surface **5** · Payments **5**

The two lowest scores are the two fixable ones: **type safety (2)** → #10/#11/#36, and **async (3)** → #37/#50.

---

## Blockers outside Pry
- `tech_debt` ledger **unbuilt fleet-wide** → no debt baseline exists to ratchet against (#21).
- **context-crypto Qdrant lane is DOWN** (embed dim mismatch 2560 vs 4096); chunk store unbuilt. The comparative agent fell back to primary vendor docs (stronger evidence, but the corpus is offline).
- Corpus skill index is missing `test-pyramid`, `flaky-test-detection`, `idempotent-jobs`.
- 3 repo-local `M` files (`scripts/check-antipatterns.py`, `scripts/antipattern_breakdown.py`, +1) predate this session and remain uncommitted.
