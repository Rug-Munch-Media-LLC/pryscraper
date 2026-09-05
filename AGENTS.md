[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# AGENTS.md — PryScraper

> AI agent contract. Read this before touching anything in this repo.

## Status
canonical · owner=crmuncher · last_updated=2026-09-05 · enterprise_grade_hardening

## What This Repo Is
Multi-source crypto intelligence crawler (pryscraper). Scraper, extractor, parser, automator, job queue. CLI + MCP server + SDK. License: Dual -- MIT (core) + BSL 1.1 (stealth/anti-detection subset). See LICENSE and LICENSE-BSL-STEALTH.

## Type
`backend` · language=Python 3.12 + FastAPI

## Where It Lives
- Source: `https://codeberg.org/cryptorugmunch/pryscraper`
- Deployed: Docker container

## Built With

## Components
- Root modules: 718 Python files (api.py, extractor.py, parser.py, etc.)
- `browser-extension/`: Chrome/Firefox extension
- `routers/`: FastAPI routers split from `api.py` (scraping, templates, health, auth, captcha, …)
- `pry_mcp/`: 104 MCP tools across 35+ categories (scraping, sports betting, crypto, prediction markets, site mapping, content filtering, etc.)
- `pry_x402/`: x402 constants + enums (split from `x402.py` 2026-07-06)
- `pry_<name>.py`: 19 root modules renamed to remove `routers/` collision (2026-07-06)
- `actor_factory/`: 112 Apify actors with PPE monetization (3 sports betting actors: intel, odds-comparison, props-engine)
- `src/pry/engine/site_mapper.py`: Firecrawl-style domain mapping + crawl-to-markdown
- `src/pry/engine/content_filter.py`: Crawl4AI-style content filtering + RAG chunking
- `datasets/sports_data/`: 60+ modules covering odds, arbitrage, +EV, props, sharp money, live analytics, weather, prediction markets, Kelly criterion, derivatives
- `datasets/prediction_markets/`: Polymarket + Kalshi live data

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
- firecrawl-style site mapping (in-house: `src/pry/engine/site_mapper.py`)
- crawl4ai-style content filtering (in-house: `src/pry/engine/content_filter.py`)

## Competitive Position
- 104 MCP tools (Firecrawl: ~6, Crawl4AI: ~4)
- 15-tier anti-bot bypass (competitors: 1-3 tiers)
- 112 Apify actors (largest fleet on Apify)
- x402 native pay-per-call (no competitor has this)
- Sports betting intelligence (no competitor offers this)

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

## Domain Boundaries (one domain -> one repo -> one owner)
Canonical contract: [standards/ARCHITECTURE.md](../standards/ARCHITECTURE.md) +
`standards/repo-domains.json`. Enforced by `.importlinter` (pre-push) and
`scripts/repo-boundary-check.sh` (pre-commit).

- **OWNS:** the web-scraping / crypto-intelligence-crawler framework — scraper,
  extractor, parser, stealth engine, captcha solver, job queue, MCP server, SDK.
- **DOES NOT own:** scanner engine / risk heuristics (rugmunch-scanner), RAG /
  retrieval (rugbrain), crypto-intelligence API + DataBus (rmi-backend), the
  Telegram client (rugmunchbot), wallet management (walletpress), and the
  codebase-reference corpus / Solidity dev trees (contextcrypto).
- **Leaf boundary:** pryscraper never imports `app`, `rugbrain`,
  `rugmunch_scanner`, `rugmunchbot`, or `walletpress` internals.

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
