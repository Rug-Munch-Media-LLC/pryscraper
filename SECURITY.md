[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# SECURITY.md — PryScraper

> Threat model, secrets, auth, rate limiting, vuln disclosure.

## Threat Model

### Assets
- User wallets (private keys never touch our servers — verified by signature)
- API keys (secrets manager)
- DB credentials (secrets manager)
- Reputation (RMM LLC brand)

### Threats
1. **Secret leak to git** — gitleaks pre-commit hook + history scan on incidents
2. **SQL injection** — SQLAlchemy ORM + parameter binding only
3. **XSS** — React auto-escapes; CSP headers on nginx
4. **CSRF** — SameSite=Strict cookies + Bearer tokens
5. **DDoS** — Cloudflare proxy in front
6. **Supply chain** — renovate keeps deps updated; pip-audit weekly

## Secrets

**Storage**: secrets manager

**Loading**:
- Local dev: `.env` file (gitignored)
- Production: docker `--env-file`, systemd `EnvironmentFile`

**Rotation**:
- API tokens: quarterly
- DB passwords: quarterly
- Signing keys: on personnel change

**Audit**: any secret leak triggers rotation within 1 hour.

## Authentication
- Bearer tokens for API
- OAuth2 (Telegram, etc) for user-facing bots
- x402 micropayments for paid endpoints (signing via Solana/EVM wallet)

## Authorization
- RBAC for admin endpoints
- Rate limiting per IP/token (sliding window)
- Admin endpoints require `cfg.admin_key` check

## Input Validation
- Pydantic models for ALL API inputs (no `dict`/`any` types)
- Length limits, regex validation, enum constraints
- Reject any input containing mainnet addresses/keys (pre-commit hook)

## Rate Limiting
- Configurable per-IP and per-token sliding window
- Returns 429 with `Retry-After` header when exceeded

## Dependencies
- `pip-audit` weekly (CI)
- `safety check` weekly (CI)
- Renovate bot for auto-PR updates

## Supported Versions

Only the latest `main` branch is supported with security updates. Older
releases and tags are not patched; users must upgrade to the current `main`
(or the latest tagged release) to receive fixes.

| Version | Supported |
|---------|-----------|
| latest `main` | ✅ |
| previous tagged release | ⚠️ best-effort, 30-day window |
| older releases | ❌ |

## Vulnerability Disclosure
Email: security@pryscraper.com (PGP key available on request)
Response within 24 hours.
Patch within 7 days for critical, 30 days for medium.

> ⚠️ **This list was aspirational; the first two no longer exist (checked
> 2026-09-30).** Corrected below.

## Audit Log
Consent/audit records are written through
`src/pry/compliance/record_store.py` (directory of JSONL record files;
`record_store` reads a directory, reports unreadable files rather than failing
silently, and the caller decides the destination).

- ✅ `src/pry/compliance/` record store — the real implementation
- ❌ `app/state/audit/` — **does not exist** in this repo (no `app/` package)
- ❌ ClickHouse audit sink — **not integrated**: no ClickHouse client or
  dependency anywhere in `src/` or `pyproject.toml`. (A `rmi-clickhouse`
  container exists in the wider fleet, but pryscraper does not write to it.)
- ❌ WORM storage (R2 with object lock) — **not implemented**: no
  `boto3`, no `object_lock`, no R2 config in `src/`. Do not tell an operator
  that 7-year WORM retention is enforced; nothing enforces it.

## Incident Response
1. Detect (alert from monitoring)
2. Contain (revoke compromised secrets, block IPs)
3. Eradicate (patch vuln, deploy fix)
4. Recover (verify systems clean, restore from backup if needed)
5. Learn (post-mortem, update SECURITY.md)
