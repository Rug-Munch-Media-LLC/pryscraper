# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### x402 Competition-Sourced Features (2026-09)
- **Pre-settle + post-settle hooks** — register callbacks before/after settlement (from JS @x402/server)
- **6-point lifecycle hooks** — verify before/after/onFailure + settle before/after (from JS @x402/server)
- **Weighted random facilitator selection** — prevents thundering herd (from Coinbase x402-py)
- **Latency-aware health scoring** — health score factors avg response time (from Coinbase x402-py)
- **Exponential backoff retry** — 3 attempts with 0.5*2^attempt delay (from Coinbase x402-py)
- **Retry-After header parsing** — honors HTTP Retry-After, 1s→30s cap (from JS @x402/server)
- **Typed error hierarchy** — VerifyError, SettleError, FacilitatorTimeoutError (from JS @x402/server)
- **Dynamic scheme negotiation** — select best scheme based on client capabilities (from Coinbase x402-py)
- **Auth-capture scheme** — authorize/capture/void flow (from JS @x402/auth-capture)
- **Auth-capture escrow PaymentInfo** — EIP-712 with expiry windows + fee bounds (from JS @x402/auth-capture)
- **Extension mutation policy** — validate extensions can't weaken security (from JS @x402/server)
- **EVM RPC fallback chain** — 2 fallback RPCs per network + retry (from Coinbase x402-py)
- **Solana payer binding** — validate on-chain authority matches expected payer
- **Health-score routing** — facilitators sorted by successes - failures*2 (from Coinbase x402-py)
- **On-chain batch channels** — voucher/claim/refund model with max_claims cap (from JS @x402/batch-settlement)
- **register_facilitator plugin point** — custom facilitator per-network (from Coinbase x402-py)

## [3.1.0] — 2026-09

Next release on top of 3.0.0: hardening the MCP server's security posture,
eliminating blocking I/O in the scraping engine, and expanding the quality
gates (mypy strict ratchet, critical-path test coverage, container supply-chain
checks). No breaking API changes.

### Added

- **CSS ReDoS guard** — regex-based denial-of-service protection on CSS
  selector parsing.
- **Browser pooling** — shared browser instances reused across requests,
  saving 1–3s per request.
- **OTEL collector + Jaeger** — OpenTelemetry trace export wired to a
  collector and Jaeger for distributed tracing.
- **Project docs** — `DECISIONS.md`, `STATUS.md`, and `PLAN.md` added.
- **Tests** — Shopify OAuth, proxy referral, CSS selector guard, browser
  pool, MCP auth gate, DB migration, and DB `import_json` test suites.
- **CI gates** — hadolint (Dockerfile lint) and grype (container
  vulnerability scan) added to the pipeline.
- **`.critical-paths` expansion** — AI Test Oracle critical-path list
  extended to cover auth, payments (x402), scraping endpoints, MCP tools,
  and DB migrations.
- **mypy strict expansion** — strict-typed module ratchet grown from 13 to
  21 modules (block_detection, dedup, errors, extraction, freshness, parser,
  paths, quality, ratelimit, resilience, retry, sessions, url_guard, plus
  pry.core.audit, pry.core.client, pry.core.config_validation,
  pry.compliance.gdpr, pry.engine.network, pry.core.secrets_backend,
  pry.core.settings, pry.engine.websocket_scraper).

### Changed

- **`pry.core.client`** — pooled HTTP client consolidated into
  `pry.core.client` (disambiguated from `pry.api.client`).
- **Healthcheck probes reconciled** — Dockerfile and docker-compose use the
  same `/health` probe.
- **cosign wired to env var** — container signing uses `COSIGN_EXPERIMENTAL`
  env var in CI.

### Fixed

- **MCP auth bypass on `/mcp/messages`** — authentication gate now enforced
  on the SSE message transport.
- **`_tier_cloudscraper` blocking in async** — blocking call removed from
  the async fallback path.
- **`get_client()` race condition** — pooled client creation made
  race-safe.
- **GDPR substring matching** — GDPR compliance matching now uses exact
  matching instead of substring matching.
- **`db_health_async` bug** — async DB health check corrected.
- **Test-ordering state bleed** — test isolation fixed so tests no longer
  leak state across runs.
- **x402 tautological test asserts** — self-referential test assertions
  replaced with meaningful checks.
- **Stale `.coverage` file** — outdated coverage artifact removed.

### Security

- **SSRF defense verified** — `resolve_dns` always `True` on URL resolution.
- **CSS selector ReDoS guard** — regex DoS protection on selector parsing.
- **MCP auth gate on SSE transport** — `/mcp/messages` now authenticated.
- **systemd unit hardened** — `User=pry`, `ProtectSystem=strict`.

### Performance

- **Pooled httpx client in 6 fallback tiers** — connection reuse across the
  adaptive fallback chain.
- **Async DNS wrapper** — non-blocking DNS resolution.
- **ResponseCache payload cap (5MB)** — cache entries bounded to prevent
  unbounded memory growth.
- **LIMIT on unbounded queries** — database queries capped.
- **Browser pooling** — 1–3s saved per request via browser reuse.

## [3.0.0] — 2026-09

Major release: the MCP server becomes the primary product surface, x402
payments reach production hardening, and the scraping engine grows to a
15-tier adaptive fallback chain.

### Added

- **MCP server with 76 tools across 33 categories** — web scraping,
  structured extraction, 110 pre-built templates, monitoring, document
  parsing, screenshots, compliance, enrichment, marketplace intelligence
  (Amazon/Walmart/TikTok Shop), sports betting (odds, arbitrage, +EV,
  props, money-printer alerts across 112+ books), crypto token
  intelligence, legal & public records, real estate, jobs, travel,
  attention/SEO, local business, government data (procurement, contracts,
  grants), IP data (patents, trademarks), climate/agri, research, and
  x402 pay-per-call pricing tools.
- **15-tier anti-detection fallback chain** — direct HTTP, TLS
  fingerprint impersonation (curl_cffi), cloudscraper, FlareSolverr,
  undetected-chromedriver, Camoufox stealth Firefox, Playwright stealth,
  Googlebot emulation, Tor, premium proxy, Archive.org, Google Cache,
  AI visual scraping, mobile app API, and GraphQL discovery — with
  per-domain adaptive tier memory and circuit breakers.
- **x402 payments** — HTTP 402 pay-per-call with server-authoritative
  pricing (64 priced operations), server-signed payment manifests
  (keccak256-ecdsa attestation), EVM (EIP-7702 self-verify) + Solana
  verification across 7 networks, Postgres-backed settlement ledger with
  JSONL audit trail.
- **Hosting portal** — Apify-console-style credit + usage dashboard,
  hosted checkout flow, crypto subscriptions (Pro/Team/Enterprise) and
  bulk scrape-credit packs, admin RBAC + audit log, key revocation and
  settlement webhooks.
- **MCP registry listings** — `server.json`, `glama.json`,
  `pulsemcp.json`, `registry_manifest.json`, and `llms.txt` kept in sync
  from `pry_mcp/tools.py`.
- **Docs site** — Docusaurus website (`website/`) covering quickstart,
  API reference, MCP, x402, and templates.

### Changed

- Tool annotations upgraded to MCP 2025-11-25 style
  (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` on
  all 76 tools).
- x402 gate buckets rate limits by real client IP behind trusted proxies
  and passes Bearer credentials for hosted keys.
- Combined tool executor wired: actor tools + 21 domain dispatchers now
  reachable from MCP.

### Fixed

- Email-verify link route and checkout/portal pages classified as
  pre-auth human surfaces.
- Payment-manifest resource URLs corrected to owned domains.
- Signed portal tokens replace email-only auth (magic-link pattern).
- 95 ruff lint errors cleared; mutation-testing baseline measured at 71%.

## [2.0.0] and earlier

See git history: <https://codeberg.org/RugMunchMedia/pryscraper/commits/branch/main>
