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
- `pry_mcp/`: 112 MCP tools across 35+ categories (scraping, sports betting, crypto, prediction markets, site mapping, content filtering, schema extraction, adaptive selectors, etc.)
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
- 112 MCP tools (Firecrawl: ~6, Crawl4AI: ~4, ScrapeGraphAI: ~3)
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

## Method memory (learned per-domain scrape method)

Pry records which scrape method actually works per **registrable domain** and
reorders the 15-tier ladder from that. Read `.claude/pry-method-memory` or
`docs/design/METHOD-MEMORY.md` before changing it.

- `engine/tier_score.rank_tiers` is the **only** ranking primitive. `best_tier`
  is derived from `reorder_for_domain`'s output — never reimplement the order.
- `scraper_orchestrate._record_tier_outcome` is the **only** writer.
- A blocked page is **never** a success, even on HTTP 200.
- Cost is charged on **failures** too — a premium-proxy request that hits a
  Cloudflare wall was still paid for.
- `PRY_RESILIENCE_PERSIST=1` is required or all learning dies on restart. It
  belongs in compose `environment:` (which shadows `env_file:`), not env_file.
- Memory keys are eTLD+1 via `engine/domain_key.memory_domain` (tldextract,
  `suffix_list_urls=()` so no runtime PSL fetch). Do not hand-roll a
  public-suffix exception list.
- `PRY_PREMIUM_PROXY_COST_USD` unset/blank/malformed/negative means **unknown**,
  never free. `tier_cost.is_cost_known()` reports the difference.

## x402 payment gate

Three credential surfaces, in gate order (see `docs/X402_SETTLEMENT_FLOWS.md`):
`owner` (`PRY_API_KEY`) → **internal** (`X-Internal-Token` + signed
`X-Internal-Timestamp`) → free paths → `Authorization: Bearer` (pays, metered)
→ else 402.

- The internal path is **fail-closed**: absent `PRY_INTERNAL_TOKEN` rejects; a
  blank/non-numeric/`<=0` `PRY_INTERNAL_MAX_SKEW_SECONDS` becomes 0 and rejects
  everything rather than widening the window.
- `caller` is **server-derived** (socket peer, or the right-most non-trusted
  `X-Forwarded-For` hop), not a name the caller chooses. Signing the wrong one
  gets a 402.
- The replay cache is consulted only **after** signature verification, so an
  attacker cannot poison it. It is per-process — correct at `--workers 1`.
- `PRY_X402_ENABLED` / `PRY_MCP_ENABLED` are **real** kill-switches read by
  `api/kill_switches.py`; default is enabled.

## Self-hosting

- `docker-compose.selfhost.yml` overlays the base file: pry + flaresolverr only,
  port **8002**, SQLite, no x402 wallet. Talos keeps **8005**.
- `PRY_API_KEY` is **mandatory** for a self-hoster: the container binds
  `0.0.0.0`, so loopback detection is false and everything 401s without it. The
  owner key is the free lane — no x402 payment is needed for your own instance.

## Gates that will block you

- `scripts/pre-commit-methodology-check.sh` — the hostname pattern requires a
  multi-label hostname, so a dotted Python import like
  `x402_middleware.internal` does not false-positive. Keep it that way.
- `scripts/check-structure.py` — shrink-only. New files must be under 200
  lines. `scraper_orchestrate.py` and `resilience.py` are allowlisted.
- Split along existing seams and verify by **diffing test output before/after**,
  not by asserting no behaviour changed.

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
