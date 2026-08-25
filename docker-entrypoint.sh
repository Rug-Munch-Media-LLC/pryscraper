#!/bin/sh
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# Pry — Docker entrypoint.
#
#   1. (optional) stamp/upgrade the database schema via Alembic.
#   2. validate configuration (logs issues; PRY_STRICT_CONFIG=1 fails fast).
#   3. start uvicorn as a child and trap SIGTERM/SIGINT so it can drain
#      in-flight requests (uvicorn --timeout-graceful-shutdown) and close
#      the httpx client / DB session pool via the app lifespan before exit.
#
# The final process is NOT exec'd so this shell can forward signals; the
# compose file runs the container with `init: true` (tini) to reap zombies.

set -e

_UV_PID=""

# ── Graceful shutdown ────────────────────────────────────────────────
# Forward the termination signal to uvicorn and wait for it to drain.
# uvicorn closes in-flight requests up to --timeout-graceful-shutdown and
# runs the app lifespan shutdown (which closes the httpx client and the
# DB engine/session pool in-process). PRY_SHUTDOWN_HOOK, if set, runs
# after uvicorn exits (e.g. a filesystem-DB cleanup command).
_shutdown() {
    echo "[pry] received shutdown signal; draining in-flight requests..."
    if [ -n "$_UV_PID" ] && kill -0 "$_UV_PID" 2>/dev/null; then
        kill -TERM "$_UV_PID" 2>/dev/null || true
        # Wait up to 35s for the graceful drain (uvicorn default grace is 30s).
        i=0
        while kill -0 "$_UV_PID" 2>/dev/null && [ "$i" -lt 35 ]; do
            sleep 1
            i=$((i + 1))
        done
        # Force-kill if the drain hung (should not happen with the timeout set).
        if kill -0 "$_UV_PID" 2>/dev/null; then
            echo "[pry] drain timed out; forcing shutdown..."
            kill -KILL "$_UV_PID" 2>/dev/null || true
        fi
        wait "$_UV_PID" 2>/dev/null || true
    fi
    if [ -n "${PRY_SHUTDOWN_HOOK:-}" ]; then
        echo "[pry] running shutdown hook: ${PRY_SHUTDOWN_HOOK}"
        sh -c "$PRY_SHUTDOWN_HOOK" || echo "[pry] shutdown hook failed (ignored)"
    fi
    echo "[pry] shutdown complete"
    exit 0
}

trap _shutdown TERM INT

# ── Database migrations ──────────────────────────────────────────────
if [ "$PRY_SKIP_MIGRATIONS" != "1" ]; then
    echo "[pry] stamping DB as up-to-date (preserves data)..."
    if ! alembic stamp head 2>/dev/null; then
        echo "[pry] stamp failed, running upgrade head..."
        alembic upgrade head
    fi
    echo "[pry] alembic current: $(alembic current 2>/dev/null || echo 'unknown')"
fi

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
        echo "[pry] configuration validation failed (strict mode); refusing to start" >&2
        exit 1
    fi
    echo "[pry] config validation skipped (config_validation/settings unavailable)" >&2
fi

# ── Start uvicorn (child) and wait ───────────────────────────────────
"$@" &
_UV_PID=$!
wait "$_UV_PID"
