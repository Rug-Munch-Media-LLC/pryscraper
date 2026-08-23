# Pry — Production Deployment Guide

Audience: operators deploying Pry for production traffic.
Companion docs: [README](README.md) · [FAQ](FAQ.md) · [Architecture](#architecture-notes)

## 1. Environment matrix

| Setting | dev | staging / prod |
|---|---|---|
| Database | embedded SQLite (`PRY_DATA_DIR/pry.db`) | **PostgreSQL** (default; SQLite needs `PRY_ALLOW_SQLITE_PROD=1`) |
| Rate limiting | in-process token bucket | Redis-backed (automatic when `PRY_REDIS_URL` reachable) |
| Auth | keyless loopback | `PRY_API_KEY` set ⇒ Bearer required from every source |
| Profile | `PRY_ENVIRONMENT=dev` | `PRY_ENVIRONMENT=prod` (or `staging`)

Resolution order for the database: explicit `PRY_DATABASE_URL` → profile
default (Postgres for prod/staging, SQLite for dev). The x402 route
classification audit runs at boot in strict mode; relax with
`PRY_X402_AUDIT=warn|off` only when you understand why.

## 2. Required secrets (never in git)

| Secret | Purpose | Source |
|---|---|---|
| `PRY_API_KEY` | API auth (fail-closed when set) | generate: `openssl rand -hex 24` |
| `PRY_WEBHOOK_SECRET` | HMAC webhook signing | gopass `pry/webhook_secret` or generate |
| `X402_WALLET` / facilitator key | payment settlement | hardware/managed KMS preferred |

Pry refuses to deliver unsigned webhooks and refuses to settle payments
without a configured facilitator — configure these before exposing traffic.

## 3. Docker Compose (recommended)

```bash
export PRY_API_KEY=$(openssl rand -hex 24)
docker compose up -d          # pry + postgres + redis + flaresolverr
curl -s http://localhost:8005/health | jq .status
```

The compose stack ships hardened defaults: digest-pinned images, non-root
container user, read-only rootfs compatible, SIGTERM drain, healthchecks.

## 4. Post-deploy checklist

- [ ] `/health` returns `ok` and `/ready` reflects Postgres+Redis connectivity
- [ ] `PRY_X402_AUDIT` boot log shows `x402_audit_clean`
- [ ] `/v1/x402/pricing` lists expected operations
- [ ] Prometheus scrapes `/metrics`; alerts from `prometheus/alerts.yml` loaded
- [ ] One paid request verified end-to-end (402 → pay → 200)
- [ ] Webhook test delivery signed and received (`POST /v1/webhooks/test`)
- [ ] Backups: Postgres dumps scheduled and restore-tested

## 5. Scaling notes

- **API tier is stateless** — scale replicas behind any LB. Sessions/jobs
  state lives in the database.
- **Rate limiting** switches to shared Redis counters automatically; without
  Redis each replica enforces its own bucket (documented behaviour).
- **Browser tiers** are the expensive path: size workers for Chromium memory
  (~300 MB per concurrent render) and prefer FlareSolverr as a sidecar pool.
- **k6 smoke** (`perf/smoke.js`, 10 VUs) gates every serving-path change in
  CI; run the nightly 50-VU profile against staging from fleet-infra.

## 6. Upgrades

1. Read the changelog; note breaking env/route changes.
2. `pip install` / pull image pinned by `requirements.lock` (never loose ranges).
3. Run migrations: `python -m db.migrations` (Alembic-backed).
4. Rolling restart behind the LB; `/ready` gates traffic shift.
5. Verify checklist §4 items 1–3 post-rollout.

## Architecture notes

- **Serving path**: uvicorn → PryHttpMiddleware (auth/rate-limit/metrics) →
  X402Middleware (payment gate) → CORS → FastAPI routers.
- **Scrape pipeline**: UltimateScraper adaptive tier chain → block-signal
  detection → extraction/quality modules (mutation-tested core).
- **Payments**: self-hosted EIP-3009 facilitator with local ecrecover,
  nonce replay store, idempotent settlement and classified RPC errors.

See `docs/specs/fetch-stack-consolidation.md` for the engine unification
roadmap and `MUTATION_BASELINE.md` for the testing-oracle methodology.
