# Spec: Fetch-Stack Consolidation (audit win #11)

Status: PROPOSED · Author: lead agent · Date: 2026-08-23
Scope: deduplicate the three overlapping fetch/render stacks before they
diverge further. This is the largest remaining audit item and needs a
dedicated session per phase.

## Problem

Three modules implement overlapping fetch/render pipelines:

| Module | LOC | Responsibilities |
|---|---|---|
| `scraper.py` | 371 | PryScraper: playwright check, `_scrape_attempt` chain |
| `ultimate_scraper.py` | 794 | UltimateScraper: 10-tier bypass chain, block detection, adaptive ordering, circuit breakers |
| `scraping_methods.py` | 1,099 | JSON-API discovery, PersistentSession, Playwright/Camoufox renderers, RSS/Atom, sitemaps |

Concrete duplication observed:
- Two Playwright render paths (`_render_with_playwright` in
  scraping_methods vs playwright tiers in ultimate_scraper/scraper).
- Two Camoufox integrations (`_render_with_camoufox` vs camoufox_integration.py).
- Three "try methods in order, record latency, fall through on failure"
  loops with subtly different retry/telemetry semantics.
- Bug fixes must be applied three times; block-detection exists in only
  one stack, so the other two cannot escalate intelligently.

## Goal

One engine interface, pluggable strategies, single telemetry path:

    FetchEngine
      ├── strategies/: direct, tls, cloudscraper, flaresolverr,
      │   undetected, camoufox, playwright, googlebot, tor, premium_proxy,
      │   archive, google_cache        (moved, not rewritten)
      ├── rendering/: playwright_renderer, camoufox_renderer (merged)
      ├── BlockDetector (single source, consulted by every strategy)
      ├── RetryPolicy + CircuitBreaker (existing resilience.py reused)
      └── Telemetry: one span/metric emission point

## Non-goals

- No behaviour change visible to API consumers (routes, payloads, prices).
- No new dependencies.
- No rewrite of parsing/extraction (already mutation-tested).

## Phases (each independently shippable)

1. **Phase 0 — Characterize (half session).** Golden-master tests over all
   three public entry points with respx-mocked upstreams; snapshot attempt
   order + telemetry events. These tests are the safety net for phases 1-3.
2. **Phase 1 — Extract rendering (session).** Merge the two Playwright and
   two Camoufox paths into `fetch_engine/rendering/`. Both old call sites
   delegate. Zero behaviour change (golden masters green).
3. **Phase 2 — Unify strategy loop (session).** Move the ten tiers into
   `fetch_engine/strategies/` behind one protocol
   (`async fetch(url, opts) -> FetchResult`). UltimateScraper keeps tier
   ordering/block-escalation but calls strategies through the protocol;
   scraper.py's attempt loop is deleted and re-expressed as a two-tier
   strategy list.
4. **Phase 3 — Delete duplicates (session).** scraping_methods keeps only
   feed/sitemap/JSON-discovery utilities (they are distinct capabilities,
   not fetch duplicates). Remove dead code, re-run mutation baseline on
   the new engine, raise coverage floor.

## Risks / mitigations

- *Stealth regressions invisible to mocks*: Phase 2 ships behind
  `PRY_FETCH_ENGINE=legacy|unified` env flag for one release; default legacy.
- *Adaptive-ordering coupling*: registry.reorder_for_domain contract gets
  its own contract tests in Phase 0.
- *x402 pricing depends on route names*: no route renames in any phase.

## Acceptance

- One Playwright renderer, one Camoufox renderer, one strategy loop.
- Golden masters unchanged across phases.
- Coverage floor +2pts after Phase 3; mutation gate run on fetch_engine.
