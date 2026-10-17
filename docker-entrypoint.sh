#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
#
# Pry — Docker entrypoint.
#
#   1. refuse to run as root (the image ships user `pry`, uid 1000)
#   2. validate PRY_DATABASE_URL (fail fast on an unusable URL)
#   3. take a pre-migration pg_dump (best effort unless strict)
#   4. apply real migrations: `alembic upgrade head` (NOT `alembic stamp`)
#   5. validate configuration (PRY_STRICT_CONFIG=1 fails fast)
#   6. start uvicorn as a child and trap SIGTERM/SIGINT so it can drain
#      in-flight requests and close the httpx client / DB pool via the app
#      lifespan before exit.
#
# The final process is NOT exec'd so this shell forwards signals; compose runs
# the container with `init: true` (tini). Escape hatches (documented in docs/ops/DEPLOY.md):
#   PRY_SKIP_MIGRATIONS=1               skip step 4 (self-host SQLite uses init_db)
#   PRY_BACKUP_BEFORE_MIGRATE=0         skip step 3
#   PRY_REQUIRE_PRE_MIGRATION_BACKUP=1  abort instead of warning if the dump fails
#   PRY_ALLOW_ROOT=1                    allow uid 0 (not supported; debug only)
#   PRY_STRICT_CONFIG=1                 fail on [ERROR]-level config issues
#   PRY_SHUTDOWN_HOOK                   command to run after uvicorn exits

set -eu

log() { printf '[pry] %s\n' "$*"; }
die() { printf '[pry] ERROR: %s\n' "$*" >&2; exit 1; }

# Volume-backed HOME/TMPDIR (compose points both at pry-data; /home/pry is a
# noexec tmpfs and /tmp is a 512m tmpfs — see docker-compose.yml).
mkdir -p "${HOME:-/app/pry-data/home}" "${TMPDIR:-/tmp}" 2>/dev/null || true
mkdir -p "${PRY_DATA_DIR:-/app/pry-data}" 2>/dev/null || true
# alembic.ini + alembic/ are copied to /app by the Dockerfile.
cd "${PRY_APP_DIR:-/app}" 2>/dev/null || true

# ── Non-root guard ───────────────────────────────────────────────────
if [ "$(id -u)" = "0" ] && [ "${PRY_ALLOW_ROOT:-0}" != "1" ]; then
    die "refusing to start as root (uid 0); the image runs as user 'pry'.
     Override with PRY_ALLOW_ROOT=1 only for debugging."
fi

# ── Graceful shutdown ────────────────────────────────────────────────
_UV_PID=""

_shutdown() {
    log "received shutdown signal; draining in-flight requests..."
    if [ -z "$_UV_PID" ]; then
        # Signal arrived during migrate/validate: nothing to drain.
        log "shutdown before app start"
        exit 143
    fi
    if kill -0 "$_UV_PID" 2>/dev/null; then
        kill -TERM "$_UV_PID" 2>/dev/null || true
        i=0
        while kill -0 "$_UV_PID" 2>/dev/null && [ "$i" -lt 35 ]; do
            sleep 1
            i=$((i + 1))
        done
        if kill -0 "$_UV_PID" 2>/dev/null; then
            log "drain timed out; forcing shutdown..."
            kill -KILL "$_UV_PID" 2>/dev/null || true
        fi
        wait "$_UV_PID" 2>/dev/null || true
    fi
    if [ -n "${PRY_SHUTDOWN_HOOK:-}" ]; then
        log "running shutdown hook: ${PRY_SHUTDOWN_HOOK}"
        sh -c "$PRY_SHUTDOWN_HOOK" || log "shutdown hook failed (ignored)"
    fi
    log "shutdown complete"
    exit 0
}

trap _shutdown TERM INT

# ── Fail fast on a bad DATABASE_URL ──────────────────────────────────
_validate_database_url() {
    _url="${PRY_DATABASE_URL:-}"
    [ -n "$_url" ] || die "PRY_DATABASE_URL is not set (e.g. postgresql://pry:pw@postgres:5432/pry)"
    case "$_url" in
        postgresql://*|postgres://*|postgresql+*://*|sqlite://*) ;;
        *) die "PRY_DATABASE_URL has an unsupported scheme: ${_url%%://*}://
     expected postgresql://, postgresql+asyncpg://, postgres:// or sqlite://" ;;
    esac
    case "$_url" in
        *'${'*) die "PRY_DATABASE_URL contains an unexpanded \${...} placeholder" ;;
        *change-me*|*replace-me*|*CHANGEME*) die "PRY_DATABASE_URL still contains a placeholder value" ;;
    esac
    if [ "${PRY_ENVIRONMENT:-dev}" = "prod" ]; then
        case "$_url" in
            *//pry:pry@*) log "WARNING: PRY_DATABASE_URL uses the default 'pry:pry' password in prod" ;;
        esac
        case "$_url" in
            sqlite*) [ "${PRY_ALLOW_SQLITE_PROD:-0}" = "1" ] || die \
                "SQLite is not allowed when PRY_ENVIRONMENT=prod; set PRY_ALLOW_SQLITE_PROD=1 or use Postgres" ;;
        esac
    fi
}

# ── Pre-migration backup guard ───────────────────────────────────────
# A dump is skipped for SQLite (a file copy is the backup) and for a brand
# new database with no tables (nothing to lose). pg_dump comes from the
# runtime image (postgresql-client-16, matching the postgres:16 server).
_pre_migration_backup() {
    [ "${PRY_BACKUP_BEFORE_MIGRATE:-1}" = "1" ] || { log "pre-migration backup disabled"; return 0; }
    case "${PRY_DATABASE_URL:-}" in
        sqlite*) log "pre-migration backup skipped (sqlite file lives on the data volume)"; return 0 ;;
        postgres*) ;;
        *) return 0 ;;
    esac
    if ! command -v pg_dump >/dev/null 2>&1; then
        if [ "${PRY_REQUIRE_PRE_MIGRATION_BACKUP:-0}" = "1" ]; then
            die "pg_dump not found but PRY_REQUIRE_PRE_MIGRATION_BACKUP=1"
        fi
        log "WARNING: pg_dump not found; continuing without a pre-migration backup"
        return 0
    fi
    _dir="${PRY_BACKUP_DIR:-${PRY_DATA_DIR:-/app/pry-data}/backups}"
    _ts="$(date -u +%Y%m%dT%H%M%SZ)"
    _file="${_dir}/pry-pre-migrate-${_ts}.dump"
    mkdir -p "$_dir" 2>/dev/null || true
    # pg_dump accepts only the plain libpq scheme; strip SQLAlchemy drivers.
    _pgurl="$(printf '%s' "${PRY_DATABASE_URL}" | sed -E 's#^(postgres(ql)?)\+[a-z0-9_]+://#\1://#')"
    if pg_dump "$_pgurl" --no-owner --no-privileges --format=custom --file "$_file" 2>/dev/null; then
        log "pre-migration backup written: ${_file}"
        # Keep the 10 most recent dumps.
        ls -1t "${_dir}"/pry-pre-migrate-*.dump 2>/dev/null | tail -n +11 | while read -r _old; do
            rm -f "$_old" || true
        done
        return 0
    fi
    if [ "${PRY_REQUIRE_PRE_MIGRATION_BACKUP:-0}" = "1" ]; then
        die "pre-migration backup failed and PRY_REQUIRE_PRE_MIGRATION_BACKUP=1"
    fi
    log "WARNING: pre-migration backup failed (continuing; set PRY_REQUIRE_PRE_MIGRATION_BACKUP=1 to abort)"
}

# ── Database migrations ──────────────────────────────────────────────
# `alembic upgrade head` applies the real revisions in alembic/versions/.
# `alembic stamp head` is deliberately NOT used: it labels an existing schema
# as current without running a single migration, which is how a clean install
# ends up with no tables and a green "current" version.
_run_migrations() {
    if [ "${PRY_SKIP_MIGRATIONS:-0}" = "1" ]; then
        log "migrations skipped (PRY_SKIP_MIGRATIONS=1)"
        return 0
    fi
    if ! command -v alembic >/dev/null 2>&1; then
        die "alembic not found on PATH; cannot migrate (set PRY_SKIP_MIGRATIONS=1 to bypass)"
    fi
    # Dump only when a revision would actually be applied — not on every
    # restart. `alembic current` prints "... (head)" once the DB is current.
    if alembic current 2>/dev/null | grep -q '(head)'; then
        log "schema already at head; no migration backup needed"
    else
        _pre_migration_backup
    fi
    log "applying migrations: alembic upgrade head"
    alembic upgrade head || die "alembic upgrade head failed — refusing to serve with a partial schema"
    log "alembic current: $(alembic current 2>/dev/null | tail -1 || echo 'unknown')"
}

_validate_database_url
_run_migrations

# ── Configuration validation ─────────────────────────────────────────
# Non-fatal by default: log issues so operators see them in `docker logs`.
# Set PRY_STRICT_CONFIG=1 to fail fast on [ERROR]-level issues.
if python -c "
import sys
from pry.core.config_validation import has_errors, validate_config
from pry.core.settings import settings

issues = validate_config(settings)
for item in issues:
    print(f'[pry-config] {item}', file=sys.stderr)
if has_errors(issues) and '${PRY_STRICT_CONFIG:-0}' in ('1', 'true', 'True'):
    sys.exit(1)
"; then
    :
else
    code=$?
    if [ "$code" -eq 1 ]; then
        die "configuration validation failed (strict mode); refusing to start"
    fi
    log "config validation skipped (config_validation/settings unavailable)"
fi

# ── Start uvicorn (child) and wait ───────────────────────────────────
"$@" &
_UV_PID=$!
set +e
wait "$_UV_PID"
_rc=$?
set -e
_UV_PID=""
exit "$_rc"
