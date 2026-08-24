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
- Source: `https://codeberg.org/cryptorugmunch/pryscraper`
- Deployed: Docker container

## Built With

## Components
- Root modules: 83 Python files (api.py, extractor.py, parser.py, etc.)
- `browser-extension/`: Chrome/Firefox extension
- `routers/`: FastAPI routers split from `api.py` (scraping, templates, health, auth, captcha, …)
- `pry_mcp/`: MCP sub-package (split from `mcp_production.py` 2026-07-06)
- `pry_x402/`: x402 constants + enums (split from `x402.py` 2026-07-06)
- `pry_<name>.py`: 19 root modules renamed to remove `routers/` collision (2026-07-06)

## Dependencies
- postgresql (job storage)
- redis (cache)
- flaresolverr (Cloudflare bypass sidecar)
- playwright (browser automation)
- cloudscraper (Cloudflare bypass tier)
- aiohttp-socks + aiohttp (SOCKS5 proxy support, async HTTP)
- pyjwt (JWT auth signing)
- apify (Apify actor SDK)
- playwright-stealth (anti-detection)

## 🚨 GIT POLICY — NON-NEGOTIABLE

1. **NEVER commit .env files, credentials, API keys, or tokens**
2. **NEVER use HTTPS remotes with embedded passwords — SSH only**
3. **NEVER commit before gitleaks passes** (`gitleaks detect --no-git`)
4. **NEVER push to main without lefthook pre-commit passing**
5. **All secrets come from gopass — NEVER hardcoded**
6. **All repos must have: .gitignore, .gitleaks.toml, .lefthook.yml**
7. **Internal IPs/hostnames use [INTERNAL] placeholder in public repos**
8. **Any agent caught leaking secrets will have their work rejected**

## 🚨 REPO-SPECIFIC RULES

1. **No nested repos.** Don't commit other complete project trees inside this one.
2. **No data blobs.** Don't commit `*.zip`, `*.parquet`, model weights, sqlite files.
3. **No broken files.** Shell heredoc accidents must be caught before commit.
4. **No duplicate scaffolds.** If a `backend/` or `frontend/` subdir exists at root, it's either THE app or bloat.
5. **Update STATUS.md before committing.** Builders must know where we are.
6. **Read DECISIONS.md before architectural changes.** Don't repeat rejected designs.
7. **Respect dual licensing.** When contributing, the core/ files are MIT (any PR welcome). The stealth/ files (listed in LICENSE-BSL-STEALTH) are BSL 1.1 -- only Rug Munch Media LLC can modify them. PRs touching BSL files will be rejected.

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
See [ARCHITECTURE.md](docs/ops/ARCHITECTURE.md). Update it when components change.

## Plan
[PLAN.md](PLAN.md) shows current sprint. Update weekly.

## Status
[STATUS.md](STATUS.md) shows where we are RIGHT NOW. Update before each commit.

## Owners
- Primary: crmuncher
- Backup: TBD

## Related Repos

## Open-Core Protection

This repo is open source (dual-licensed MIT + BSL). The code here demonstrates
HOW to build a web scraping API — it is NOT the complete RugMunch production
setup. The RugMunch managed platform at rugmunch.io includes proprietary
enhancements (internal scraping infrastructure, admin dashboard, enterprise
features).

See [CONTRIBUTING.md](CONTRIBUTING.md) for our methodology approach.
for details on what information belongs in public vs private repos.

## Git Policy

This repo:
- Classification: OPEN SOURCE — web scraping framework
- Remotes: codeberg + github + gitlab + radicle (primary)
- Commits: type(scope): description
- Never commit: .env, secrets, internal IPs, security reports
