# DEPLOY — clean install, verified

Two supported profiles. **Self-host** is the clean-install path (two
containers, SQLite). **Production** is the fleet profile (Postgres + Redis +
monitoring). Both use the same image and the same entrypoint.

Everything below follows the **current** code path. Where a step is still
manual, it says so.

---

## 0. What the container does at boot

`docker-entrypoint.sh` runs, in order:

1. **Refuses root.** `refusing to start as root (uid 0)` — the image runs as
   `pry` (uid 1000). `PRY_ALLOW_ROOT=1` is debug-only.
2. **Validates `PRY_DATABASE_URL`.** Empty, unknown scheme, an unexpanded
   `${...}`, or a `change-me` placeholder exits non-zero with `[pry] ERROR:`.
3. **Pre-migration backup** (Postgres only, and only when a revision is
   actually pending). Writes
   `$PRY_DATA_DIR/backups/pry-pre-migrate-<UTC>.dump`, keeps the last 10.
   Failure warns unless `PRY_REQUIRE_PRE_MIGRATION_BACKUP=1`.
4. **Applies migrations**: `alembic upgrade head`. It does **not** run
   `alembic stamp head` — stamping labelled an empty database as current and
   was the clean-install bug.
5. **Validates config.** Non-fatal by default; `PRY_STRICT_CONFIG=1` fails
   closed.
6. **Starts uvicorn**, traps `SIGTERM`/`SIGINT`, drains up to 35 s, exits with
   uvicorn's status.

Boot log (healthy production):

```
[pry] applying migrations: alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade ...
[pry] alembic current: 0009_x402_user_id_and_hosting_tables (head)
INFO:     Uvicorn running on http://0.0.0.0:8002
```

---

## 1. Self-host install (10 commands)

Requires Docker Engine 24+ and **Compose v2.24+** (the overlay uses
`!override` / `!reset`, and `env_file.required`).

```bash
# 1  get the code
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git && cd pryscraper

# 2  confirm the compose version — expect v2.24.0 or newer
docker compose version

# 3  create the env file (safe defaults, no secrets)
cp .env.selfhost.example .env.selfhost

# 4  generate PRY_API_KEY into .env.selfhost (idempotent)
./scripts/selfhost-init.sh
#   -> [selfhost] wrote /.../.env.selfhost with a generated PRY_API_KEY.

# 5  render the merge BEFORE building
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost config -q
#   -> no output, exit 0

# 6  build and start (pry + flaresolverr-pry only)
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost up -d --build
#   -> Container pry-flaresolverr-pry  Started
#   -> Container pry                   Started

# 7  container state — both must be (healthy)
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost ps
#   -> ... Up ... (healthy)   ... Up ... (healthy)

# 8  liveness — 200 with the version
curl -fsS http://127.0.0.1:8002/healthz
#   -> {"status":"ok","version":"x.y.z"}

# 9  authenticated scrape
KEY=$(grep '^PRY_API_KEY=' .env.selfhost | cut -d= -f2-)
curl -fsS -X POST http://127.0.0.1:8002/v1/scrape \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url":"https://example.com"}'
#   -> {"success":true,"data":{"markdown":"...","metadata":{...}}}

# 10 stop (data survives in the pry-data volume)
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost down
```

### Self-host read this before filing a bug

* **`/health` returns 503 here by design.** It gates on Redis **and**
  Postgres; this profile runs neither (SQLite + in-process limiter). The
  container healthcheck therefore points at `/healthz` (liveness). `docker
  compose ps` showing `(healthy)` is correct.
* **`PRY_SKIP_MIGRATIONS=1`** — the SQLite schema is created by the app's
  `init_db()`, not Alembic. Moving to Postgres means setting
  `PRY_DATABASE_URL=postgresql://...` and `PRY_SKIP_MIGRATIONS=0`; the
  entrypoint then runs the migrations. **That migration path is manual** —
  rehearse it on a copy first (`docs/ops/UPGRADE.md`).
* **TLS is manual.** The API binds `127.0.0.1:8002`. Put nginx/Caddy in front;
  set `PRY_PUBLIC_BASE_URL=https://...` and keep `PRY_TRUSTED_PROXIES` limited
  to the proxy (it currently trusts Docker's `172.16.0.0/12` plus loopback).
* **No proxy / no CAPTCHA key** in this profile — hard Cloudflare targets will
  fail. That is configuration, not a defect.

---

## 2. Production install (fleet profile, Postgres + Redis)

Still 10 commands, but with real secrets. `POSTGRES_PASSWORD` and
`GRAFANA_PASSWORD` are mandatory (`:?` in the compose file); the app secrets
file supplies `PRY_API_KEY`.

```bash
# 1  code
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git && cd pryscraper

# 2  compose v2.24+
docker compose version

# 3  interpolation values (project .env, git-ignored)
cp .env.example .env
printf 'POSTGRES_PASSWORD=%s\nGRAFANA_PASSWORD=%s\n' \
  "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" >> .env

# 4  app secrets — OUTSIDE the repo (compose reads it with required:false)
install -d -m 700 /srv/rmi-infra
printf 'PRY_API_KEY=%s\n' "$(openssl rand -hex 24)" > /srv/rmi-infra/.env.pry
chmod 600 /srv/rmi-infra/.env.pry

# 5  render
docker compose config -q          # -> no output, exit 0

# 6  build + start everything
docker compose up -d --build

# 7  state — pry/postgres/redis must be healthy
docker compose ps

# 8  readiness (Redis + DB up -> 200)
curl -fsS http://127.0.0.1:8005/health
#   -> {"status":"ok","version":"...","dependencies":{"redis":true,"database":true,...}}

# 9  migrations actually applied
docker compose logs --tail=40 pry | grep -E 'alembic|migrations'
#   -> [pry] applying migrations: alembic upgrade head
#   -> [pry] alembic current: ... (head)

# 10 authenticated scrape
KEY=$(grep '^PRY_API_KEY=' /srv/rmi-infra/.env.pry | cut -d= -f2-)
curl -fsS -X POST http://127.0.0.1:8005/v1/scrape \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url":"https://example.com"}'
```

Production pins an image tag: set `PRY_IMAGE_TAG=v1.4.2` (or a digest) in
`.env`. The compose default `${PRY_IMAGE_TAG:-latest}` is a local-build
convenience — never deploy `latest` implicitly.

**Manual today:** TLS termination, the fleet DataBus URL (`PRY_DATABUS_URL`,
deliberately kept out of the repo), gopass/Webshare credentials, and DNS.
Nothing in the repo automates those.

---

## 3. Clean-install checklist — tick all 12

| # | Check | Exact command | Success looks like |
|---|---|---|---|
| 1 | Compose ≥ 2.24 | `docker compose version --short` | `v2.24.0` or newer |
| 2 | Daemon reachable | `docker info --format '{{.ServerVersion}}'` | a version string, exit 0 |
| 3 | Port free | `ss -ltn 'sport = :8002'` | no output |
| 4 | API key generated | `grep -c '^PRY_API_KEY=replace-me' .env.selfhost` | `0` |
| 5 | Merge renders | `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml --env-file .env.selfhost config -q` | no output, exit 0 |
| 6 | Image builds | `docker compose -f docker-compose.yml -f docker-compose.selfhost.yml --env-file .env.selfhost build pry` | exit 0 |
| 7 | Stack starts | `... up -d` (same flags) | both containers `Started` |
| 8 | Both healthy | `... ps --format '{{.Name}} {{.Health}}'` | `pry healthy`, `...flaresolverr-pry healthy` |
| 9 | No boot errors | `... logs pry` then look for `ERROR`/`Traceback` | none |
| 10 | Liveness | `curl -fsS http://127.0.0.1:8002/healthz` | `{"status":"ok",...}`, exit 0 |
| 11 | Auth + scrape | the `/v1/scrape` command from step 9 | `"success":true` |
| 12 | Data persists | `... restart pry`, repeat checks 10–11 | still 200; `docker volume ls` lists `pry-data` |

If check 9 shows `ERROR: PRY_DATABASE_URL is not set`, the `--env-file` flag
was omitted. If it shows `refusing to start as root`, something overrode the
image `USER` — do not disable the guard in production.
