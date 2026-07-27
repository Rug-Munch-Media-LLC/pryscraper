[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# DEPLOYMENT.md — PryScraper

> How to deploy. Build, push, restart, rollback.

## Architecture
- Container: Docker
- Image registry: local/private
- Orchestration: docker-compose
- Reverse proxy: nginx
- Auto-deploy: forgejo webhook → deploy script

## Deploy

### Automatic (CI/CD)
On merge to `main`:
1. forgejo webhook fires
2. Deploy script pulls latest commit
3. Rebuilds Docker image
4. Stops old container, starts new
5. Runs health check
6. Rolls back on failure

### Manual
```bash
# On the deploy host
cd /srv/pryscraper
git pull origin main
docker build -t pryscraper:latest .
docker stop pryscraper && docker rm pryscraper
docker run -d --name pryscraper --restart unless-stopped --network host -p 8005:8005 pryscraper:latest
```

### Schema Migrations (Alembic)

The container entrypoint (`docker-entrypoint.sh`) runs Alembic before starting uvicorn:

1. `alembic stamp head` — idempotent. Marks the DB as up-to-date without running migrations (preserves existing data when schema already matches).
2. On stamp failure: `alembic upgrade head` — applies pending migrations from scratch.
3. `exec "$@"` — chains to the CMD (uvicorn).

`PRY_SKIP_MIGRATIONS=1` skips the migration step entirely (for read-only debug runs).

Manual migration commands:
```bash
docker exec pry alembic current
docker exec pry alembic history
docker exec pry alembic upgrade head   # apply pending
docker exec pry alembic stamp head     # mark up-to-date without applying
```

Create a new migration:
```bash
docker exec pry alembic revision --autogenerate -m "describe the change"
# then COPY the file out, review, commit to pryscraper repo
docker cp pry:/app/alembic/versions/<new>.py ./alembic/versions/
```

## Health Check
```bash
curl -fsS http://localhost:8005/health
```

## Rollback
```bash
# On the deploy host
cd /srv/pryscraper
git log --oneline -5   # find last good commit
git checkout <commit-hash>
docker build -t pryscraper:latest .
docker restart pryscraper
```

## Logs
```bash
docker logs pryscraper --tail 100 -f
```

## Monitoring
- Prometheus: `/metrics` endpoint
- Grafana: dashboards
- Loki: log aggregation

## Secrets
All secrets in a secrets manager (e.g. gopass, 1Password, vault).

Loaded via docker `--env-file` or systemd `EnvironmentFile`.

## Firewall
- Public ports: nginx
- Internal: localhost only, behind nginx

## Backup
- Code: forgejo (source of truth)
- Data: DB snapshot daily
- Config: secrets manager
