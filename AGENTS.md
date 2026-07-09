[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# AGENTS.md — PryScraper

> AI agent contract. Read this before touching anything in this repo.

## Status
canonical · owner=crmuncher · last_updated=2026-07-06 · phase_0_hardening_complete

## What This Repo Is
Multi-source crypto intelligence crawler (pryscraper). Scraper, extractor, parser, automator, job queue. CLI + MCP server + SDK. License: Dual -- MIT (core) + BSL 1.1 (stealth/anti-detection subset). See LICENSE and LICENSE-BSL-STEALTH.

## Type
`backend` · language=Python 3.12 + FastAPI

## Where It Lives
- Source: `https://git.rugmunch.io/RugMunchMedia/pryscraper`
- Deployed: Docker on Talos (/srv/pry/)
- Port: 8005

## Built With
- Standards: [git.rugmunch.io/RugMunchMedia/standards](https://git.rugmunch.io/RugMunchMedia/standards)
- Toolchain: [TOOLCHAIN.md](https://git.rugmunch.io/RugMunchMedia/standards/raw/branch/main/TOOLCHAIN.md)
- Conventions: [CONVENTIONS.md](https://git.rugmunch.io/RugMunchMedia/standards/raw/branch/main/CONVENTIONS.md)

## Components
- `/srv/pry/*.py`: 83 Python modules (api.py, extractor.py, parser.py, etc.)
- `browser-extension/`: Chrome/Firefox extension
- `routers/`: FastAPI routers split from `api.py` (scraping, templates, health, auth, captcha, …)
- `pry_mcp/`: MCP sub-package (split from `mcp_production.py` 2026-07-06)
- `pry_x402/`: x402 constants + enums (split from `x402.py` 2026-07-06)
- `pry_<name>.py`: 19 root modules renamed to remove `routers/` collision (2026-07-06)

## Dependencies
- postgresql (job storage)
- redis (cache)
- flaresolverr (Cloudflare bypass, on Hydra)
- playwright (browser automation)
- cloudscraper (Cloudflare bypass tier)
- aiohttp-socks + aiohttp (SOCKS5 proxy support, async HTTP)
- pyjwt (JWT auth signing)
- apify (Apify actor SDK)
- playwright-stealth (anti-detection)

## 🚨 CRITICAL RULES

1. **No nested repos.** Don't commit other complete project trees inside this one.
2. **No secrets.** Never commit `.secrets/`, `.env`, `*.pem`, `*.key`, `*.crt`. Use gopass.
3. **No data blobs.** Don't commit `*.zip`, `*.parquet`, model weights, sqlite files.
4. **No broken files.** Shell heredoc accidents must be caught before commit.
5. **No duplicate scaffolds.** If a `backend/` or `frontend/` subdir exists at root, it's either THE app or bloat.
6. **Update STATUS.md before committing.** Builders must know where we are.
7. **Read DECISIONS.md before architectural changes.** Don't repeat rejected designs.
8. **Respect dual licensing.** When contributing, the core/ files are MIT (any PR welcome). The stealth/ files (listed in LICENSE-BSL-STEALTH) are BSL 1.1 -- only Rug Munch Media LLC can modify them. PRs touching BSL files will be rejected.

## Commands
```bash
make install       # install deps
make dev           # dev server
make test          # tests
make lint          # ruff + format check
make typecheck     # mypy strict
make security      # bandit + gitleaks
make ci            # full pipeline
make commit        # conventional commit
make clean         # remove build artifacts
```

## Architecture
See [ARCHITECTURE.md](ARCHITECTURE.md). Update it when components change.

## Plan
[PLAN.md](PLAN.md) shows current sprint. Update weekly.

## Status
[STATUS.md](STATUS.md) shows where we are RIGHT NOW. Update before each commit.

## Owners
- Primary: crmuncher
- Backup: TBD

## Related Repos
See [standards/PRODUCTS.md](https://git.rugmunch.io/RugMunchMedia/standards/raw/branch/main/PRODUCTS.md).
