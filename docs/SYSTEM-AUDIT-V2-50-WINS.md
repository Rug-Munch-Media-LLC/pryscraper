# Pry Audit V2 — 50 Same-Day Wins to Enterprise Grade
_Fresh audit 2026-08-25, post src/pry-restructure. Suite 3,732 green,
pyright 0, both sites live. This list is what stands between here and
enterprise-grade. Every item scoped to be completable in one day._

## A. FINISH THE PACKAGE MIGRATION (1–8) — the restructure is 70% done
1. Move `db/` package → `src/pry/core/db/`; delete `src/pry/core/db.py`
   shim; rewrite 14 `from db import` sites.
2. Move `routers/` (83 files) → `src/pry/api/routers/`; update api.py
   imports; delete root routers/.
3. Move `captcha/` → `src/pry/engine/captcha/` (registry + 6 solvers).
4. Move `x402/` + `x402_middleware.py` → `src/pry/payments/x402/`;
   create `payments/__init__.py` facade (audit move 10).
5. Move `llm_providers/` → `src/pry/intelligence/llm/`; registry+base+
   providers together.
6. Move `marketplace/`, `billing/`, `referrals/`, `signup/` →
   `src/pry/commerce/` siblings; kill pyproject manual includes.
7. Delete build artifacts from tree: `dist/`, `pry.egg-info/`,
   `pryscraper_mcp.egg-info/`, `__pycache__/` at root; add to .gitignore.
8. Decide + relocate product dirs (`browser-extension/`, `shopify-app/`,
   `wordpress-plugin/`, `workers/`, `site_catalog/`) → own repos or
   `products/` — they are not part of the Python engine.

## B. TESTING GAPS (9–20) — coverage measured 42.5% on core paths
9. Raise `middleware.py` coverage from 43.8% → 80% (lines 82–155 auth
   paths + 388–509 metrics path are dark).
10. Add router smoke test: parametrized import + route registration for
    all 83 routers (catches broken imports instantly).
11. Contract-test the Apify SDK surface used by runner (push_data/charge
    semantics in ONE fake, reused everywhere).
12. Wire `tests/contract` + `tests/fuzz` into ci.yml (exist, not gated).
13. Remove phantom `--ignore=tests/integration` from all commands.
14. Fix or delete the 5 skipped tests (Postgres via compose service).
15. Hypothesis property tests for ActorSpec invariants (lint-clean,
    unique FAQs, price bands) — would catch congruency drift.
16. Golden-file snapshot of one full generated actor package; diff in CI.
17. Coverage gate on changed files (diff-cover) at 85%, not repo average.
18. Weekly mutmut job vs MUTATION_BASELINE.md; publish delta.
19. Test AbuseGuard against random failure sequences (hypothesis).
20. Integration test: full actor run against a local httpbin fixture —
    proves fetch→process→charge end-to-end.

## C. CI / WORKFLOWS (21–28) — several jobs failing on config, not code
21. Fix `.forgejo/workflows/apify-actor.yml` publish job (CLI v1.x has no
    `--token`; use login or API deploy). Currently dead.
22. Update ci.yml paths: remove `--ignore=tests/integration`, old module
    names; add `datasets/` to lint/test scope.
23. perf-smoke.yml references pre-restructure paths — repoint to src/pry.
24. Triage scorecard/release-please/supply-chain failures (need tokens or
    workflow config; code gates pass locally).
25. Pin Docker base by digest: `apify/actor-python-playwright@sha256:...`
    + Renovate for digest bumps.
26. Add SBOM (syft) per actor package at build; attach artifact.
27. Cache pip + npm in CI (install time dominates wall clock).
28. Required checks: make `test` + `lint` branch-protection required.

## D. ACTOR FACTORY & CATALOG (29–36)
29. Bump catalog version to 1.1 before Store launch (recipe-miner carries
    26 debug builds under 1.0).
30. Generate per-family Store screenshots from live-fire outputs (docs/
    verification data → PNG cards).
31. Add `datasets.*` imports to generated-actor dependency scan (some
    vertical Actors will need them).
32. Runtime smoke per API-backed actor family in CI (10 URLs, 60s budget)
    — catches upstream API drift weekly.
33. llms.txt: append individual actor list (name + one-liner ×94) —
    currently families only.
34. Add canonical link tags on /faq and /docs/apify (308s exist today).
35. Self-hosted analytics (umami) on landing + docs; measure what works.
36. Feed live-fire results into each README as a "Last verified" line +
    date — trust signal, auto-updated by the verification script.

## E. CODE QUALITY (37–43)
37. Split `scraping_methods.py` (1,099 lines) → `engine/methods/*` (move 7).
38. Split `processors.py` (~750 lines) → `processors/{extraction,audit,
    monitoring,commerce}.py` registry (move 8).
39. Burn down 36 bare `except Exception` without noqa — classify each:
    specific type, or add documented noqa.
40. TypedDict return shapes per processor (catches shape bugs at type
    check; the array-truncation bug class).
41. Split `x402_middleware.py` (961 lines) into enforcement/config/
    fallback modules under payments/.
42. Deduplicate shared constants (headers, UA pools, regexes) into
    `engine/constants.py` — single source of truth.
43. mypy: enable strict on `src/pry/core` + `actor_factory` first (they
    are clean); expand outward per package.

## F. SECURITY & OPS (44–50)
44. Gitleaks scan inside staged actor packages before upload (defense in
    depth in publish.py).
45. Verify user_ratelimit wired to ALL api routes (spot-check says yes;
    write the assertion test).
46. Nightly export of Apify account state (actors, schemas) to B2 —
    restore points for platform outage.
47. Incident runbook: Apify build failing / platform API change / abuse
    storm — one page, three flows, on-call ready.
48. Dependency freshness: run check-dep-flake script, file issues for
    >2yr-old deps, schedule quarterly.
49. Backups: verify alembic migrations run clean on fresh Postgres
    (docker compose up → migrate → assert tables).
50. Publish STATUS.md from live data (suite count, catalog size, last
    verification date) — generated, not hand-written.

## Execution order for TODAY
Morning: 21–24 (CI honest), 29 (version bump), 7 (artifacts out)
Afternoon: 1–2 (db+routers move), 9–11 (coverage gaps), 30 (screenshots)
Evening: 36, 33, 44–45 (trust + security polish), 50 (status page)
