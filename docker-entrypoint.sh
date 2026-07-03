#!/bin/sh
set -e

if [ "$PRY_SKIP_MIGRATIONS" != "1" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

exec "$@"
