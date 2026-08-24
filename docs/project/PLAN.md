[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# PLAN.md — PryScraper

> Current sprint. 21-day cycles per ADR-0012.

## Status
current_sprint=2026-Q3-S1 · started=2026-07-01 · ends=2026-07-21

## Sprint Goals
1. DONE Re-license to dual MIT + BSL 1.1 (ADR-0002) - done 2026-07-03
2. WIP Deploy repo to server - wire the new api.py (4,668 lines, 190 endpoints) so MCP and x402 actually serve
3. WIP Wire auth - JWT/API-key middleware on the live deploy so we can monetize

## In Progress
- [x] Re-license the codebase: dual MIT (core) + BSL 1.1 (stealth)
- [x] Add SPDX headers to all 300+ files
- [x] Write ADR-0002 documenting the decision
- [ ] Deploy updated api.py with MCP and x402 endpoints to server
- [ ] Set PRY_X402_WALLET and PRY_X402_FACILITATOR env vars
- [ ] Run templates/validate_templates.py end-to-end, publish honest success rate

## Backlog (this sprint)
- [ ] Migrate ~/.pry/* JSON storage to SQLite (concurrency + multi-tenant)
- [ ] Split api.py (4,668 lines) into router modules (cap 500 lines each)
- [ ] Replace 159 broad except Exception with specific types + add ruff BLE001
- [ ] Surface proxy_referrals.py and referrals.py in /v1/referrals API
- [ ] Publish browser extension (Chrome Web Store) and WordPress plugin (wordpress.org)
- [ ] Deploy Cloudflare Worker mcp-worker.js so MCP server is publicly hosted
- [ ] Register on Smithery, Glama, PulseMCP MCP directories
- [ ] Build pry.dev landing page with comparison table (Pry vs Firecrawl vs ScrapingBee)

## Risks
- TODO: anything blocking progress

## Done (this sprint)
- _None yet — sprint just started._

## Carry-over from previous sprint
- _None._

---

## Definition of Done
- [ ] Code complete
- [ ] Tests written (>80% coverage on changed lines)
- [ ] Pre-commit hooks pass (ruff, mypy, gitleaks, bandit)
- [ ] CI passes on forgejo
- [ ] Conventional commit message
- [ ] PR reviewed + merged
- [ ] Deployed to staging
- [ ] Smoke-tested in production
- [ ] Observability in place (metrics, logs, alerts)
- [ ] Docs updated (AGENTS.md, ARCHITECTURE.md, README.md)
- [ ] STATUS.md updated
