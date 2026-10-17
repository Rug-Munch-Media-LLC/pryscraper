# UPGRADE — backup → pull → migrate → verify → rollback

The entrypoint runs `alembic upgrade head` **before** uvicorn starts, so
`docker compose up -d` is a migrating deploy. This runbook makes that
explicit and reversible.

Rule: **never upgrade without a dump you have actually seen on disk.**

---

## 0. Pre-flight (2 minutes)

```bash
# what is running now
docker compose ps --format '{{.Name}} {{.Image}} {{.Status}}'
# record it — this is your rollback target
docker compose images | tee /tmp/pry-images-before.txt

# current revision
docker compose exec -T pry alembic current
#   -> 0009_x402_user_id_and_hosting_tables (head)

# free space for the dump (dumps are ~database size)
df -h /var/lib/docker
```

Pin what you are running now in `.env` (`PRY_IMAGE_TAG=...`) before changing
anything. `latest` gives you no rollback target.

---

## 1. Backup (see BACKUP-RESTORE.md for the full model)

Production (Postgres):

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T postgres pg_dump -U pry -d pry \
  --no-owner --no-privileges --format=custom > "pry-${TS}.dump"
ls -lh "pry-${TS}.dump"
#   -> non-zero size, e.g. -rw-r--r-- 1 root root 4.2M ...
```

Self-host (SQLite):

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost exec -T pry python -c \
  "import sqlite3;s=sqlite3.connect('/app/pry-data/pry.db');d=sqlite3.connect('/tmp/pry.db');s.backup(d);d.close();s.close()"
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost cp pry:/tmp/pry.db "pry-${TS}.db"
```

Also copy `.env` / `.env.selfhost` / the secrets env file — a database
restore without the matching keys is a different outage.

---

## 2. Pull and build

```bash
git pull --ff-only
git log --oneline -5              # confirm the expected commits

# pin the NEW tag in .env: PRY_IMAGE_TAG=v1.5.0
docker compose build pry
docker compose up -d              # recreates pry; entrypoint migrates
```

Self-host: use the same two `-f` files and `--env-file .env.selfhost`.

---

## 3. Migrate — what actually happens

On start the entrypoint:

1. validates `PRY_DATABASE_URL` (bad URL = exit, no partial boot);
2. dumps the DB to `$PRY_DATA_DIR/backups/` **if** a revision is pending;
3. runs `alembic upgrade head`; a failure exits non-zero and the container
   does **not** serve;
4. logs the resulting revision.

To migrate ahead of the app (maintenance window, pre-flight):

```bash
docker compose run --rm --entrypoint alembic pry upgrade head
docker compose run --rm --entrypoint alembic pry current
```

`alembic stamp head` is never used — it marks revisions as applied without
running them.

---

## 4. Verify

```bash
docker compose ps                 # pry must be (healthy)
docker compose logs --tail=60 pry | grep -E 'alembic|migrations|ERROR'
#   -> [pry] alembic current: <new head>
#   -> no ERROR

curl -fsS http://127.0.0.1:8005/health   # production — 200
curl -fsS http://127.0.0.1:8002/healthz  # self-host  — 200

# capability smoke (same body as the deploy runbook)
KEY=$(grep '^PRY_API_KEY=' /srv/rmi-infra/.env.pry | cut -d= -f2-)
curl -fsS -X POST http://127.0.0.1:8005/v1/scrape \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url":"https://example.com"}' | head -c 200
```

If `/health` is 503 while `/healthz` is 200, a critical dependency is down
(Redis or database) — fix that before blaming the release.

---

## 5. Rollback

Two levels, in order of preference.

**A. App rollback (schema unchanged or backward-compatible):**

```bash
# set PRY_IMAGE_TAG back to the value in /tmp/pry-images-before.txt
docker compose up -d
docker compose ps
```

**B. Schema rollback (migration broke compatibility):**

Do **not** assume revisions are reversible. Most are forward-only; a
`downgrade` that drops a column loses data. The canonical rollback is the
dump from step 1:

```bash
docker compose stop pry
docker compose exec -T postgres pg_restore -U pry -d pry \
  --clean --if-exists --no-owner < "pry-${TS}.dump"
docker compose up -d postgres      # confirm healthy
docker compose up -d pry           # previous PRY_IMAGE_TAG
```

`alembic downgrade -1` is only valid if that revision ships a working
`downgrade()`; check `alembic/versions/` before relying on it.

Self-host: stop `pry`, copy the `.db` backup back into the `pry-data` volume,
then start.

---

## 6. Post-upgrade

* Confirm the pre-migration dump exists and prune older ones if you keep
  your own copies: `ls -lt $PRY_DATA_DIR/backups` inside the container.
* Record the new revision and tag in the change ticket.
* If the release changed an env var, update `.env.selfhost` from
  `.env.selfhost.example` — the file is the contract.
