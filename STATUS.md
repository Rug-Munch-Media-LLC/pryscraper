[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# STATUS.md — PryScraper

> Where we are RIGHT NOW. Update before every commit.

## Last Updated
2026-07-06 - Test fixes landed; Alembic opt-out + Shopify OAuth + Zoho stub + Apify .actor/src/main.py + make actor-build pushed; Phase 0 hardening still complete

## Current Status
🟢 production-ready - Phase 0 hardening complete (JWT fail-closed, secrets backend, metrics endpoint, router split, dep pinning, missing-cloudscraper/aiohttp-socks/pyjwt/apify wired, cli recursion killed, parser.tmp deleted). Canonical main aligned with upstream.

## Deployment Status
- **Last deploy**: TBD (next deploy picks up Phase 0 hardening)
- **Current version**: 3.0.0
- **Health**: TBD
- **Uptime (30d)**: TBD
- **Active branch**: `main` (aligned with `upstream/main`)

## Open Issues
- _None — track in forgejo issues_

## Recent Activity
- 2026-07-02: Repository created from `fleet-template`
- 2026-07-03: Split scraping endpoints from `api.py` into `routers/scraping.py` + `deps.py`
- 2026-07-03: Split template endpoints into `routers/templates.py` + added `POST /v1/templates/batch`
- 2026-07-03: Added e2e tests for scraping and template routers (23 new/passing)
- 2026-07-03: Added reusable Apify actor schema builder (`apify_schema.py`)
- 2026-07-03: Set `PRY_API_KEY` in Talos `/srv/pry/.env`; auth now active on restart
- 2026-07-03: Added `/v1/templates/batch` to x402 paid endpoints + pricing
- 2026-07-03: Added `/metrics` endpoint + Prometheus counters/histograms for requests and scrapes
- 2026-07-03: Added Redis + Postgres services to `docker-compose.yml`
- 2026-07-03: Fixed Ollama URL to [INTERNAL_HOST]
- 2026-07-03: Added `LLMRegistry.complete_or_empty()` graceful fallback
- 2026-07-03: Regenerated `requirements.txt`; added pinned `requirements.lock`
- 2026-07-06: Phase 0 hardening cherry-picked onto main: JWT fail-closed (already subsumed by canonical), secrets_backend integration, captcha_solver wire-in, validate_live.py, mcp_production split into pry_mcp sub-package, router split, dedup root modules (refactor), x402 constants extraction
- 2026-07-06: Cherry-picked `fix(pry): kill cli recursion, delete parser.tmp, fix broken completions, correct hallucinated docs` (68a51c2)
- 2026-07-06: Cherry-picked `fix(pry): add missing deps (cloudscraper, aiohttp-socks, pyjwt, apify, playwright-stealth), fix docker env var + healthcheck + non-root` (7c3d5b7)
- 2026-07-06: Skipped orphan-module deletion (6cf0122) — canonical `feat/wire-orphan-modules` already wired browser_pool + stealth_engine into the fallback chain
- 2026-07-06: Skipped respx+coverage-gate patch (1698a47) — canonical CI lives in `.forgejo/workflows/ci.yml`, not `.github/`

## Known Issues / Tech Debt
- Deploy at `/srv/pry/` is out of sync with repo (needs pull + restart to activate Phase 0 hardening)
- `feat/phase0-rebased` branch reconciles infra-hardening commits on top of latest `main`
- pry-flaresolverr host port moved from 8191 to 8192 to avoid conflict with `rmi-flaresolverr`
- All 80+ site templates unverified - only ~30-40% known to work end-to-end. Run templates/validate_templates.py before claiming template coverage.
- State storage in ~/.pry/*.json - no concurrency safety, no transactions. See plan to migrate to SQLite/Postgres.
- PRY_X402_WALLET, PRY_X402_FACILITATOR env vars unset in deploy - x402 payments not active.
- License collision resolved 2026-07-03: dual MIT (core) + BSL 1.1 (stealth/anti-detection). See ADR-0002.
- mcp_production.py and x402.py exist in repo but are NOT deployed. Top priority for next deploy.
- `test_ready_returns_200` is now `@pytest.mark.integration` and deselected by default; run with `pytest -m integration` against a live Postgres+Redis stack.
- `test_structure_monitor.py` autouse fixture now resets both `db._engine` and `client.http_client` per test; defeats the DB-pollution + closed-event-loop patterns that surfaced when the suite grew past 600 tests.

## Quick Links
- [Live URL](https://[INTERNAL])
- [API docs](https://[INTERNAL]/docs)
- [Health](https://[INTERNAL]/health)
- [Repo](https://git.rugmunch.io/RugMunchMedia/pryscraper)

## Status Indicators
Use these in commit messages + status updates:
- 🟢 healthy — deployed, monitored, no issues
- 🟡 degraded — running but with known issues
- 🔴 down — service unavailable
- 🚧 in-development — pre-production, expect breakage
- ⏸️ paused — work intentionally stopped
