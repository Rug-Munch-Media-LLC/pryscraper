# BACKUP & RESTORE

Back up **four** things. A database dump alone is not a restore.

| What | Where | Why |
|---|---|---|
| Database | `pry-postgres` volume (or `pry-data/pry.db` for self-host) | keys, metering, billing, ledger, audit log |
| App data | `pry-data` volume | `config.json`, camoufox cache, pre-migration dumps |
| Secrets | `/srv/rmi-infra/.env.pry`, project `.env`, `.env.selfhost` | a restored DB is unusable without the same keys |
| Image tag | `PRY_IMAGE_TAG` in `.env` | rollback needs the exact build, not `latest` |

Sessions (`pry-sessions`) are disposable — cookie jars are re-warmable.

---

## 1. Database — production (Postgres)

The `postgres:16` container ships `pg_dump` 16, matching the server. Use it;
a host `pg_dump` 15 cannot dump a 16 server.

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T postgres pg_dump -U pry -d pry \
  --no-owner --no-privileges --format=custom > "pry-${TS}.dump"
ls -lh "pry-${TS}.dump"     # must be non-zero
```

Custom format (`-Fc`) restores selectively with `pg_restore` and compresses.
Verify it is readable before trusting it:

```bash
docker compose exec -T postgres pg_restore --list < "pry-${TS}.dump" | head
#   -> archive TOC listing table/index entries
```

**Automated already:** the entrypoint writes a dump before applying pending
migrations to `$PRY_DATA_DIR/backups/pry-pre-migrate-<UTC>.dump` and keeps the
last 10. That covers upgrades, **not** disk loss — copy dumps off the host.

Daily off-host (manual, recommended):

```bash
docker compose exec -T postgres pg_dump -U pry -d pry -Fc \
  | ssh backup-host 'cat > /backups/pry-$(date -u +%Y%m%d).dump'
```

---

## 2. Database — self-host (SQLite)

Use SQLite's online backup API; copying a live `.db` can capture a torn write.

```bash
FILES="-f docker-compose.yml -f docker-compose.selfhost.yml --env-file .env.selfhost"
docker compose $FILES exec -T pry python -c \
  "import sqlite3;s=sqlite3.connect('/app/pry-data/pry.db');d=sqlite3.connect('/tmp/pry.db');s.backup(d);d.close();s.close()"
docker compose $FILES cp pry:/tmp/pry.db "pry-$(date -u +%Y%m%dT%H%M%SZ).db"
```

---

## 3. App data volume

`config.json` holds runtime overrides; the camoufox cache is re-downloadable
(660 MB) and may be excluded to save space.

```bash
VOL=$(docker volume ls --format '{{.Name}}' | grep 'pry-data$' | head -1)
echo "$VOL"
docker run --rm -v "${VOL}:/data:ro" -v "$PWD:/backup" alpine \
  tar czf "/backup/pry-data-$(date -u +%Y%m%dT%H%M%SZ).tgz" -C /data \
  --exclude=home/.cache --exclude=tmp .
ls -lh pry-data-*.tgz
```

Stop `pry` first if you want a byte-consistent copy:
`docker compose stop pry` → tar → `docker compose start pry`.

---

## 4. Restore — rehearsed checklist

Run this on a **scratch host or a spare project name** at least quarterly.
A restore path that has never been executed is a hope, not a backup.

1. **Provision clean.** `git clone` the same tag; create `.env` with the same
   `PRY_IMAGE_TAG`, `POSTGRES_PASSWORD`; restore the secrets env file.
   Success: `docker compose config -q` exits 0.
2. **Start only the database.** `docker compose up -d postgres`.
   Success: `docker compose ps postgres` → `(healthy)`.
3. **Restore the dump.**
   `docker compose exec -T postgres pg_restore -U pry -d pry --clean --if-exists --no-owner < pry-YYYY.dump`
   Success: exit 0 (warnings about existing objects are normal on a non-empty DB).
4. **Check the revision.** `docker compose run --rm --entrypoint alembic pry current`
   Success: prints a revision; if it prints nothing the dump was empty — stop.
5. **Restore the data volume** (if you backed it up):
   `docker run --rm -v "$VOL:/data" -v "$PWD:/backup" alpine tar xzf /backup/pry-data-YYYY.tgz -C /data`
   Success: `config.json` present inside the volume.
6. **Start the app.** `docker compose up -d`.
   Success: `pry` reaches `(healthy)`; logs show `alembic current: ... (head)`
   and no `Traceback`.
7. **Prove the data, not just the process.** `curl -fsS .../health` → 200;
   run one authenticated `/v1/scrape` (success: `"success":true`); read one
   record that must exist — e.g. a known API-key row or the latest ledger
   entry — via the app's own endpoint or `psql`.
8. **Record the drill.** Date, dump name, restore duration, revision, and any
   step that differed from this document. Fix the document, not the memory.

### Restore gotchas

* Restoring into a **running** app: the app may hold connections and cache
  stale rows. Stop `pry` first.
* `pg_restore --clean` drops and recreates objects; it does not drop the
  database. If the dump came from a newer schema, follow with
  `alembic upgrade head`.
* Self-host: replace `pry-data/pry.db` only while `pry` is stopped, then start
  it. The entrypoint skips migrations (`PRY_SKIP_MIGRATIONS=1`).
* A dump is only as good as its **secrets**. Without the original
  `PRY_API_KEY` / signing keys, existing clients fail authentication even
  though the data restored cleanly.
