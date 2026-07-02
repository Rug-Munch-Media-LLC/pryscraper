[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# STATUS.md — PryScraper

> Where we are RIGHT NOW. Update before every commit.

## Last Updated
2026-07-03 - Dual-licensing relicense complete (MIT core + BSL 1.1 stealth)

## Current Status
🟡 pre-production - repo scaffolded, re-license landed, deploy out of sync. See AUDIT.md.

## Deployment Status
- **Last deploy**: TBD
- **Current version**: TBD
- **Health**: TBD
- **Uptime (30d)**: TBD
- **Active branch**: `main`

## Open Issues
- _None — track in forgejo issues_

## Recent Activity
- 2026-07-02: Repository created from `fleet-template`

## Known Issues / Tech Debt
- Repo and deploy at /srv/pry/ are out of sync. Deploy runs a 789-line api.py; repo has 4,668-line api.py with 190 endpoints (MCP, x402, auth, etc.). MCP and x402 are written but not deployed. See AUDIT.md.
- All 80+ site templates unverified - only ~30-40% known to work end-to-end. Run templates/validate_templates.py before claiming template coverage.
- State storage in ~/.pry/*.json - no concurrency safety, no transactions. See plan to migrate to SQLite.
- PRY_API_KEY, PRY_X402_WALLET, PRY_X402_FACILITATOR env vars unset in deploy - no auth, no x402, no payments.
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
