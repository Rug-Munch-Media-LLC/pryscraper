#!/bin/sh
set -e

if [ "$PRY_SKIP_MIGRATIONS" != "1" ]; then
    echo "[pry] stamping DB as up-to-date (preserves data)..."
    if ! alembic stamp head 2>/dev/null; then
        echo "[pry] stamp failed, running upgrade head..."
        alembic upgrade head
    fi
    echo "[pry] alembic current: $(alembic current 2>/dev/null || echo 'unknown')"
fi

exec "$@"
