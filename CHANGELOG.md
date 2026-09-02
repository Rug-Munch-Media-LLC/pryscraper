# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
