# Pry Full System Audit — 2026-08-24
_Scope: engine, actor factory, API/MCP, tests, docs, website, packaging, ops._
_Verdict: strong core (3,732 green tests, 79 lint-clean Actors, real anti-abuse),
undermined by one structural decision — a flat 95-module root — plus doc sprawl,
stale public claims, and thin integration wiring._

## A. STRUCTURE & PACKAGING (the big one)
1. **Flatten the root into `src/pry/` package.** ~95 modules sit bare at repo
   root, enumerated by hand in `py-modules = [...]`. Every new file needs a
   manual pyproject edit; two modules already collided once (`_JSONLD_RE`
   defined twice). Move to `src/pry/<domain>/` with auto-discovery.
2. **Domain subpackages**: `engine/` (scraper, methods, proxy, resilience,
   stealth), `actors/` (factory+runner+processors), `api/`, `mcp/`, `billing/`,
   `compliance/`. Root keeps only `pyproject.toml`, `README.md`, `LICENSE`.
3. **Kill the manual py-modules list** — packages auto-include; delete 95 lines
   of config that can drift.
4. **Consolidate 29 root `.md` files** into `docs/` with an index. Overlap:
   AUDIT/DECISIONS/PLAN/ROADMAP/FEATURES all describe overlapping state.
   Keep at root: README, LICENSE, CHANGELOG, SECURITY, CONTRIBUTING, AGENTS.
5. **Vertical data dirs** (`*_data/` ×~15) → single `datasets/` or out-of-repo
   artifact storage; they're content, not code.
6. **Delete local junk**: `mutants/` (613 mutmut output files), empty
   `warmed_cookies/`, ensure `.gitignore` covers `mutants/`, `dist/`.
7. **Split `scraping_methods.py` (1,099 lines)** into per-method modules under
   `engine/methods/`; it's the #1 complexity hotspot and merge-conflict magnet.
8. **Split `processors.py` (~750 lines)** into `processors/{extraction,audit,
   monitoring,commerce}.py` registry pattern before it doubles again.
9. **Deduplicate regex/constant definitions** — audit for shared constants
   living in multiple modules (the JSON-LD bug class).
10. **Move `x402.py`/`x402_middleware.py` + `pry_mcp/` behind one `payments/`
    interface** so x402 can evolve without touching scrape paths.

## B. TESTING GAPS
11. **Coverage ratchet 75→77** (measured 76.0%; the TODO says do it).
12. **Wire `tests/contract` + `tests/fuzz` + `tests/k6` into CI** — they exist
    but aren't in the default gate; contract tests against rmi-backend need a
    service fixture or explicit skip-documentation.
13. **Fix or delete the 5 skipped tests** (Postgres-dependent, SSE-hang,
    tor-fallback): give SSE a streaming-safe client test; spin Postgres via
    docker compose in CI; tor test → marked integration.
14. **Remove phantom `--ignore=tests/integration`** from standard commands —
    directory doesn't exist; rename `tests/contract` intent accordingly.
15. **Mutation testing cadence**: MUTATION_BASELINE.md exists but mutmut runs
    aren't scheduled — add weekly CI job, track delta vs baseline.
16. **Property-based tests for the factory**: hypothesis strategies for
    ActorSpec (random inputs/events) asserting invariants (lint-clean,
    unique FAQs, price bands). Would have caught congruency issues earlier.
17. **Golden-file test for generated Actor packages**: snapshot one full
    staged package; any unintended generator change fails CI loudly.
18. **AbuseGuard chaos test**: random failure sequences via hypothesis;
    assert never aborts when success rate > threshold.
19. **Contract tests for Apify platform**: mock apify SDK push_data/charge
    semantics in one place (currently faked ad hoc in several test files).
20. **Coverage gate on changed files** (covgate/diff-cover) rather than only
    whole-repo average.

## C. DOCUMENTATION
21. **Fix README badges**: GitHub links point to nonexistent
    `codeberg.org/RugMunchMedia`; CI badge uses Forgejo URL.
    Point badges at Codeberg/Forgejo properly or drop them.
22. **Sync llms.txt: "60 store-ready actors" → 79** (stale public claim).
23. **Expand sitemap.xml** (5 URLs) — add docs pages, comparison pages, blog.
24. **One "Start Here" doc**: DEVELOPMENT.md vs CONTRIBUTING.md vs AGENTS.md
    overlap; new-contributor path should be a single annotated journey.
25. **ADR backfill**: ADRs 0000-0002 exist; write ADRs for the four big calls:
    flat→src layout, PPE pricing tiers, AbuseGuard policy, JSON-LD-first
    extraction strategy.
26. **ACTOR-STANDARDS.md ↔ linter parity test**: every rule in the standards
    doc must have a corresponding linter check (and vice versa) — enforce
    with a test that parses both.
27. **Publish MARKET-ANALYSIS.md summary to pryscraper.com** (trust content,
    SEO long-tail: "apify actor pricing study").
28. **Doc freshness stamps**: small front-matter `last-reviewed:` dates +
    a quarterly CI reminder issue.

## D. WEBSITE / FRONTEND
29. **Landing has 5 pages** — add `/actors` catalog page (generated from
    ALL_PRESETS at build time), `/pricing` (the four tiers), `/changelog`.
30. **Cross-link landing ↔ docs** prominently both directions; today docs
    theme matches but navigation between them is disconnected.
31. **Replace og.svg with real OG images** per page (1200×630) — social
    sharing currently renders generic.
32. **Add privacy-friendly analytics** (self-hosted umami/plausible) to
    landing + docs; you can't improve what you don't measure.
33. **Mobile audit of landing**: Lighthouse mobile run; fix whatever CLS/tap
    targets fall out (docs got this pass; landing hasn't).
34. **Comparison pages**: add vs-Bright-Data and vs-Decodo (real competitors
    buyers compare); each links to relevant Actors.
35. **llms.txt full regeneration** from ALL_PRESETS at build time (actor
    names + one-liners), not hand-maintained.

## E. CONFIG / OUTPUT CORRECTNESS
36. **Fix `.forgejo/workflows/apify-actor.yml` publish job** — CLI v1.x
    removed `push --token`; switch to login-state or API-based publish.
37. **Generated Dockerfile pinning**: base image tag
    `apify/actor-python-playwright:3.13` floats — pin digest + Renovate
    automation for digest bumps.
38. **requirements.actor.lock generation is runtime-derived** — add CI check
    that ACTOR_RUNTIME_PACKAGES all resolve on python 3.13 (dry pip install).
39. **Emit SBOM per Actor package** (syft already in fleet standards) —
    attach at build, store as artifact.
40. **Actor versioning strategy**: bump catalog to v1.1 pre-launch so Store
    listings start clean (recipe-miner carries 26 debug builds under 1.0).

## F. CODE QUALITY
41. **Burn down the 20-error mypy baseline** in engine imports — mostly
    no-any-return; fix per-module, then tighten config.
42. **Type the processor protocol** — `ProcessorFn` returns dict[str, Any];
    introduce TypedDict item shapes per processor family (catches shape bugs
    like the array-truncation class at type-check time).
43. **Unify charge/push semantics** — `push_and_charge` charges errors too;
    make skip-vs-error billing policy explicit config with docs (refund-
    storm prevention is product, not just code).
44. **Structured logging review**: ensure every warning/error in runner/
    guard carries run_id binding (partially there; finish it).
45. **Dead code sweep**: vulture runs in hooks but results aren't gated —
    triage current list, delete or annotate.

## G. SECURITY & OPS
46. **Secrets scan in Actor packages**: gitleaks runs repo-wide; add a
    staged-package scan step in publish.py before upload (defense in depth).
47. **Rate-limit the public API** (`api.py`) — user_ratelimit.py exists;
    verify it's wired to all routes, not just some.
48. **Backups for Apify account state**: export actor definitions + results
    schemas nightly to B2 (platform is authoritative but we should hold
    restore points).
49. **On-call runbook**: DEPLOYMENT.md covers deploys; add incident flows
    (Apify build failing, platform API changes, abuse storm playbook).
50. **Quarterly dependency freshness**: libyear/check-dep-drift script exists
    — schedule it, publish a dashboard number, act on >2yr-old deps.

## Priority order for execution
Week 1: 1-3 (package restructure), 21, 22, 36, 40 (launch blockers)
Week 2: 7-8 (hotspot splits), 11-14 (test gates), 29-30 (site catalog)
Week 3: 16-20 (property/golden/mutation), 41-45 (quality burn-down)
Ongoing: docs consolidation, website expansion, ops hardening
