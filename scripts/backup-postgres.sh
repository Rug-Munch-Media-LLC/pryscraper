#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Off-host PostgreSQL backup + verified restore test for Pry.
#
#   scripts/backup-postgres.sh                 # dump, checksum, upload, rotate
#   scripts/backup-postgres.sh --restore-test  # newest dump -> temp DB -> counts
#   scripts/backup-postgres.sh --file X.dump --restore-test
#
# Env:
#   PRY_DATABASE_URL / DATABASE_URL   source database (required)
#   PRY_BACKUP_DIR                    default: ${PRY_DATA_DIR:-/app/pry-data}/backups
#   BACKUP_RETENTION_DAYS             local rotation window (default 30)
#   B2_BUCKET, B2_PREFIX              off-host upload (Backblaze B2)
#   B2_CLI                            b2 client path (default: b2 on PATH)
#   B2_OPTIONAL=1                     warn instead of failing when B2 has no client
#   PRY_RESTORE_ADMIN_URL             admin DSN for --restore-test (default: /postgres)
#   PG_DUMP_BIN / PG_RESTORE_BIN / PSQL_BIN   overrides (tests, pinned clients)
#
# The dump is written as a .part file and renamed only on success, so a failed
# pg_dump never leaves a truncated file that looks restorable. Each dump has a
# sha256 sidecar; --restore-test verifies it before restoring.
set -euo pipefail

PART_FILE=""
RESTORE_DB=""
RESTORE_ADMIN=""
log() { printf '[backup] %s\n' "$*" >&2; }

cleanup() {
    rm -f "${PART_FILE:-}"
    if [ -n "$RESTORE_DB" ]; then
        "$PSQL_BIN" "$RESTORE_ADMIN" -q \
            -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\"" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
die() {
    printf '[backup] ERROR: %s\n' "$*" >&2
    exit 1
}

PG_DUMP_BIN="${PG_DUMP_BIN:-pg_dump}"
PG_RESTORE_BIN="${PG_RESTORE_BIN:-pg_restore}"
PSQL_BIN="${PSQL_BIN:-psql}"
BACKUP_DIR="${PRY_BACKUP_DIR:-${PRY_DATA_DIR:-/app/pry-data}/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
RESTORE_TEST=0
DUMP_FILE=""

usage() {
    cat >&2 <<'EOF'
scripts/backup-postgres.sh                 # dump, checksum, upload, rotate
scripts/backup-postgres.sh --restore-test  # newest dump -> temp DB -> counts
scripts/backup-postgres.sh --file X.dump --restore-test
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
    --restore-test)
        RESTORE_TEST=1
        shift
        ;;
    --file)
        [ $# -ge 2 ] || die "--file requires a path"
        DUMP_FILE="$2"
        shift 2
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *) die "unknown argument: $1 (see --help)" ;;
    esac
done

RAW_URL="${PRY_DATABASE_URL:-${DATABASE_URL:-}}"
[ -n "$RAW_URL" ] || die "PRY_DATABASE_URL (or DATABASE_URL) is required"
case "$RAW_URL" in
postgresql+*://* | postgres+*://*)
    # Strip SQLAlchemy drivers: libpq accepts only postgres(ql)://.
    DB_URL="postgresql://${RAW_URL#*://}"
    ;;
postgresql://* | postgres://*) DB_URL="$RAW_URL" ;;
*) die "unsupported DSN scheme: ${RAW_URL%%://*}://" ;;
esac

timestamp() { date -u +%Y%m%dT%H%M%SZ; }

latest_dump() {
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pry-*.dump' -print 2>/dev/null |
        sort | tail -n 1
}

verify_checksum() {
    local dump="$1" sidecar="$1.sha256"
    [ -f "$sidecar" ] || {
        log "no checksum sidecar for $(basename "$dump"); skipping verify"
        return 0
    }
    (cd "$(dirname "$dump")" && sha256sum -c "$(basename "$sidecar")" >/dev/null) ||
        die "checksum verification failed for $dump"
    log "checksum OK: $(basename "$dump")"
}

rotate_local() {
    [ -d "$BACKUP_DIR" ] || return 0
    local removed
    removed="$(find "$BACKUP_DIR" -maxdepth 1 -type f \
        \( -name 'pry-*.dump' -o -name 'pry-*.dump.sha256' \) \
        -mtime +"$RETENTION_DAYS" -print -delete | wc -l)"
    log "rotation: removed ${removed} file(s) older than ${RETENTION_DAYS}d"
}

upload_offsite() {
    local dump="$1" base prefix
    base="$(basename "$dump")"
    prefix="${B2_PREFIX:-pry/postgres}"
    if [ -z "${B2_BUCKET:-}" ]; then
        log "B2_BUCKET unset; dump stays local only (not off-host)"
        return 0
    fi
    if [ -n "${B2_CLI:-}" ] || command -v b2 >/dev/null 2>&1; then
        local cli="${B2_CLI:-b2}"
        "$cli" upload-file "$B2_BUCKET" "$dump" "$prefix/$base"
        "$cli" upload-file "$B2_BUCKET" "$dump.sha256" "$prefix/$base.sha256"
        log "uploaded to b2://$B2_BUCKET/$prefix/$base"
        return 0
    fi
    if command -v aws >/dev/null 2>&1 && [ -n "${B2_ENDPOINT:-}" ]; then
        aws --endpoint-url "$B2_ENDPOINT" s3 cp "$dump" "s3://$B2_BUCKET/$prefix/$base"
        aws --endpoint-url "$B2_ENDPOINT" s3 cp "$dump.sha256" "s3://$B2_BUCKET/$prefix/$base.sha256"
        log "uploaded via aws s3 to b2://$B2_BUCKET/$prefix/$base"
        return 0
    fi
    if [ "${B2_OPTIONAL:-0}" = "1" ]; then
        log "WARNING: B2_BUCKET set but no b2/aws client; continuing (B2_OPTIONAL=1)"
        return 0
    fi
    die "B2_BUCKET is set but no 'b2' or 'aws' client is available (set B2_OPTIONAL=1 to allow local-only)"
}

take_backup() {
    mkdir -p "$BACKUP_DIR"
    local target part
    target="$BACKUP_DIR/pry-$(timestamp).dump"
    part="${target}.part"
    PART_FILE="$part"
    log "dumping $target"
    "$PG_DUMP_BIN" "$DB_URL" --no-owner --no-privileges \
        --format=custom -Z6 --file "$part" || die "pg_dump failed"
    [ -s "$part" ] || die "pg_dump produced an empty file"
    mv "$part" "$target"
    PART_FILE=""
    (cd "$BACKUP_DIR" && sha256sum "$(basename "$target")" >"${target}.sha256")
    verify_checksum "$target"
    upload_offsite "$target"
    rotate_local
    log "backup complete: $target ($(du -h "$target" | cut -f1))"
}

db_url_for() {
    local name="$1" admin="$2"
    printf '%s' "$admin" | sed -E "s#/[^/?]+(\?.*)?\$#/${name}\1#"
}

restore_test() {
    local dump admin tmpdb restored count tables table
    dump="${DUMP_FILE:-$(latest_dump)}"
    [ -n "$dump" ] && [ -f "$dump" ] || die "no dump found (pass --file or run a backup first)"
    verify_checksum "$dump"

    admin="${PRY_RESTORE_ADMIN_URL:-$(printf '%s' "$DB_URL" | sed -E 's#/[^/?]+(\?.*)?$#/postgres\1#')}"
    tmpdb="pry_restore_test_$(date -u +%s)_$$"
    restored="$(db_url_for "$tmpdb" "$admin")"
    RESTORE_DB="$tmpdb"
    RESTORE_ADMIN="$admin"

    log "restore test: $dump -> $tmpdb"
    "$PSQL_BIN" "$admin" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"$tmpdb\""
    "$PG_RESTORE_BIN" --no-owner --no-privileges -d "$restored" "$dump" >/dev/null ||
        die "pg_restore failed"

    tables="x402_payment_records usage scrape_jobs"
    for table in $tables; do
        count="$("$PSQL_BIN" "$restored" -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM $table")" ||
            die "restore test: SELECT count(*) failed on $table"
        log "restore test: $table count=$count"
    done
    log "restore test PASSED ($dump)"
}

if [ "$RESTORE_TEST" = "1" ]; then
    restore_test
else
    take_backup
fi
