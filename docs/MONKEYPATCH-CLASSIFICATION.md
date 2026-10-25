# Monkeypatch classification — pryscraper (2026-10-25)

Headline `git grep -hoE 'monkeypatch|MONKEYPATCH|# *HACK|# *WORKAROUND|# *TEMP'` = **3,079**.

## Reality by class

| class | definition | src | datasets | tests | scripts+docs | total |
|---|---|---|---|---|---|---|
| a — test patching | pytest `monkeypatch` fixture / `mock.patch` | 0 | 0 | 2,812 | 0 | 2,812 |
| b — executable source monkeypatch | `setattr(<module>, "attr")` / `mod.attr = fn` | **0** | **0** | 0 | 0 | **0** |
| c — `# HACK` / `# WORKAROUND` / `# TEMP` markers | comment markers | 0 | 0 | 0 | 0 | **0** |
| d — prose / string mentions | comments + docstrings *describing* test seams (not code) | 30 | 36 | 112 | 89 | 267 |

Token truth: `monkeypatch` 3,088 (overlapping-line recount), `MONKEYPATCH` 0,
`# HACK` 0, `# WORKAROUND` 0, `# TEMP` 0.

**Real count = 0 executable source monkeypatches, 0 debt markers.**
The "3,034 headline" is 91% pytest's `monkeypatch` fixture plus prose.

## sed-audited `setattr(` in production (all legitimate, no module patching)
- `src/pry/commerce/hosting/persistence.py:146` — `setattr(row, key, value)` (dataclass row)
- `src/pry/core/middleware_common.py:138` — `setattr(root, _ROUTE_CACHE_ATTR, ...)` (app state)
- `src/pry/core/settings.py:243,281,283,286` — settings loader onto `self`

## The real debt: production shaped around test patching (DI violation, 68 sites)
Late-bound module handles / re-exports that exist only so tests can patch:
`billing/{subscription,subscription_time,subscription_invoices,subscription_verify,settlement,packs,verify,clock}.py`,
`hosting/{__init__,settlement,signup,persistence}.py`, `payments/x402/facilitator{,_self_hosted}.py`,
`payments/x402_middleware/enforcement.py`, `api/routers/core/{admin,admin_shared}.py`,
`api/routers/scraping/{crawl_adaptive,extraction_llm,extraction_thumbnail}.py`,
`engine/{resilience,ultimate_scraper,tier_health_store}.py`,
`datasets/sports_data/*` (books, offshore*, european*, sources_*, alerts*, props, odds_multi, alt_lines),
`datasets/commerce_data/marketplaces*`, `datasets/travel/hotels*.py`.
Fix path: constructor-injected `clock`, `http_client`, `facilitator`, `registry` (one seam, no module globals).

## Flagged tests (patch our own config/logic; weak assertion surface)
- `tests/test_middleware.py:406` patches `pry.core.middleware.settings.api_key`; asserts only `app.assert_awaited_once()` — passes even if auth were checked.
- `tests/test_middleware.py:433,457,475` same pattern (mock app, no negative assertion).
- `tests/test_camoufox_cookies.py:18` `patch.object(camoufox_integration, "_has_camoufox", True)` — module flag patch, should be an injected capability probe.
- 22 further tests use mock-call assertions only (`assert_awaited_once`), acceptable for I/O isolation but blind to logic regressions.

## Ratchet
`scripts/check-monkeypatch.py` now also counts `# HACK|# WORKAROUND|# TEMP` and
`setattr(<module>, "attr", ...)`; self-source excluded; baseline re-frozen **1217 → 4**
(stale baseline counted tests the scanner no longer scans).
Proof: planted `# HACK` → 4→5 FAIL rc=1; planted quoted `setattr` → FAIL rc=1;
positional `setattr(os.environ, ...)` → PASS (not a patch); clean tree → PASS rc=0.
