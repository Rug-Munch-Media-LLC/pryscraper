[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# STATUS.md — PryScraper

> Where we are RIGHT NOW. Update before every commit.

## Last Updated
2026-07-03 - Phase 0 infra hardening: metrics, redis/postgres, pinned deps, scrape metrics

## Current Status
🟡 pre-production - router split deployed; infra hardening branch ready for review/deploy.

## Deployment Status
- **Last deploy**: TBD
- **Current version**: 3.0.0-phase0
- **Health**: TBD
- **Uptime (30d)**: TBD
- **Active branch**: `feat/phase0-rebased` (reconciled on top of latest `main`)

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
- 2026-07-03: Fixed Ollama URL to Talos (`100.104.130.92:11434`)
- 2026-07-03: Added `LLMRegistry.complete_or_empty()` graceful fallback
- 2026-07-03: Regenerated `requirements.txt`; added pinned `requirements.lock`

## Known Issues / Tech Debt
- Deploy at `/srv/pry/` is out of sync with repo (needs pull + restart to activate PRY_API_KEY, router changes, and metrics)
- `feat/phase0-rebased` branch reconciles infra-hardening commits on top of latest `main`
- pry-flaresolverr host port moved from 8191 to 8192 to avoid conflict with `rmi-flaresolverr`
- All 80+ site templates unverified - only ~30-40% known to work end-to-end. Run templates/validate_templates.py before claiming template coverage.
- State storage in ~/.pry/*.json - no concurrency safety, no transactions. See plan to migrate to SQLite/Postgres.
- PRY_X402_WALLET, PRY_X402_FACILITATOR env vars unset in deploy - x402 payments not active.
- License collision resolved 2026-07-03: dual MIT (core) + BSL 1.1 (stealth/anti-detection). See ADR-0002.
- mcp_production.py and x402.py exist in repo but are NOT deployed. Top priority for next deploy.
- All 80+ site templates unverified - only ~30-40% known to work end-to-end. Run templates/validate_templates.py before claiming template coverage.
- State storage in ~/.pry/*.json - no concurrency safety, no transactions. See plan to migrate to SQLite/Postgres.
- PRY_X402_WALLET, PRY_X402_FACILITATOR env vars unset in deploy - x402 payments not active.
- License collision resolved 2026-07-03: dual MIT (core) + BSL 1.1 (stealth/anti-detection). See ADR-0002.
- mcp_production.py and x402.py exist in repo but are NOT deployed. Top priority for next deploy.

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
