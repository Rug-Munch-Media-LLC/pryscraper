<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright (c) 2026 Rug Munch Media LLC -->
# DECISIONS — PryScraper Architecture Decision Records

> Read before architectural changes. Don't repeat rejected designs (AGENTS.md).
> Companion to `docs/project/DECISIONS.md` (index) + `docs/adr/NNNN-*.md`.

## ADR-001: src-layout migration (pry_* root modules → src/pry/)
### Status: Accepted
### Context
Flat root modules (`api.py`, `pry_*.py`) + root `routers/` collided with the `pry` package name, broke installed entry points, and made packaging/import-linter fragile.
### Decision
Migrate runtime modules under `src/pry/<domain>/` (src-layout); `packages.find` ships the `pry` tree; entry points retarget `pry.misc.cli`. Domains folded incrementally (A1 db→`pry.core.db`, A2 routers→`pry.api.routers`, A4 x402→`pry.payments`, A6 commerce→`pry.commerce`).
### Consequences
Clean packaging/boundaries; `pytest` needs `pythonpath=["src","."]` during the dual-layout transition. Migration still in flight (A1–A8).

## ADR-002: Dual licensing (MIT core + BSL stealth)
### Status: Accepted
### Context
Pry is public OSS, but the anti-detection/stealth subset is competitive IP that must not be freely modifiable by third parties.
### Decision
Dual license: MIT core (`LICENSE`) + BSL 1.1 stealth subset (`LICENSE-BSL-STEALTH`). Only Rug Munch Media LLC may modify BSL files; PRs touching them are rejected.
### Consequences
Public OSS reach with protected stealth methodology; contributors must respect the BSL boundary.

## ADR-003: 15-tier fallback scraping chain
### Status: Accepted
### Context
A single fetch strategy fails against modern anti-bot (Cloudflare, WAF, TLS fingerprinting). Prior design was a 10-tier chain; targets vary per domain.
### Decision
`UltimateScraper.tier_order` builds a 15-tier adaptive chain (direct → TLS impersonation → cloudscraper → FlareSolverr → undetected-chromedriver → Camoufox → Playwright → Googlebot → premium proxy → Tor → Archive.org → Google Cache → AI visual → mobile app API → GraphQL). Per-domain adaptive tier memory (`adaptive.py`) reorders tiers; each tier has a circuit breaker + retry config.
### Consequences
High resilience with graceful degradation; more moving parts — mitigated by browser pooling (ADR-007).

## ADR-004: MCP server dual-mode (SDK + fallback)
### Status: Accepted
### Context
The MCP server must run over stdio and HTTP/SSE without hard-depending on the `mcp` SDK being importable.
### Decision
`sdk_server.py` uses the official MCP Python SDK when present, else a pure-httpx stdio server. Entry points (`pry-mcp`, `pryscraper-mcp`) boot the same click command (`pry mcp serve`).
### Consequences
Portable MCP server with graceful SDK degradation; fallback must stay in sync with SDK behavior (tracked as `FallbackMCPServer` god-class debt).

## ADR-005: x402 payment integration
### Status: Accepted
### Context
Pry monetizes per-call via crypto micropayments; needs server-authoritative pricing, replay hardening, and multi-chain verification without a paid facilitator dependency.
### Decision
Implement x402 v1 in `src/pry/payments/x402/`: HTTP 402 pay-per-call, server-authoritative pricing (64 ops), keccak256-ecdsa attestation, EIP-7702 self-verify + Solana + TRON across 7 networks, Postgres settlement ledger with JSONL audit trail. `X402Middleware` is the outermost ASGI gate so a keyless agent reaches the 402 challenge before auth rejects with 401.
### Consequences
Self-hosted, no external facilitator required (opt-in `PRY_X402_SELF_FACILITATE`); adds crypto/ledger complexity and a security-critical verification surface.

## ADR-006: Import-linter domain boundaries (4 contracts)
### Status: Accepted
### Context
Routers imported engine internals directly, and Pry must never import backend/rag/scanner/bot/product internals from sibling repos.
### Decision
`.importlinter` defines 4 contracts: (1) domain independence, (2) routers stay thin (no engine imports), (3) core stays pure (no API/payments imports), (4) Pry never imports sibling repo internals. Enforced pre-push; known intentional edges exempted via `ignore_imports` until a `pry.services` layer exists.
### Consequences
Enforced domain boundaries and repo independence; `pry.services` extraction remains the long-term fix for exempted engine-composition edges.

## ADR-007: Browser pooling (per-request → shared)
### Status: Accepted
### Context
Launching a Playwright/Camoufox/undetected-chromedriver browser per request cost 1–3s per attempt and leaked browser processes.
### Decision
Pool browsers: launch once, `new_context`/fresh page per request. Playwright and Camoufox reuse a pooled browser; uc driver reused with `threading.Lock` serialization. `close_browsers()` wired to app lifespan shutdown.
### Consequences
1–3s saved per attempt and clean shutdown; pooled browsers must NOT be quit inside the scrape loop (ownership moved to the pool).

## ADR-008: ResponseCache in-memory LRU (not Redis-backed)
### Status: Accepted
### Context
Content caching needed low-latency reads without a hard Redis dependency for every deployment.
### Decision
`ResponseCache` is an in-memory LRU with cache caps. Redis remains an optional shared cache/rate-limit layer (and backs the MCP session store for horizontal scaling), but the response cache itself is process-local.
### Consequences
Zero-dependency fast caching; cache not shared across replicas — horizontal scaling relies on Redis for session state, not content cache.

---
Last updated: 2026-09-02
