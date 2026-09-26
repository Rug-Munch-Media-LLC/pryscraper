#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
#
# selfhost-init.sh — prepare .env.selfhost for the two-container self-host
# profile. Generates a strong PRY_API_KEY (never committed) and leaves every
# other value at the documented defaults. Idempotent: an existing key is
# preserved so re-running does not invalidate clients.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.selfhost"
ENV_EXAMPLE="${REPO_ROOT}/.env.selfhost.example"

if [ ! -f "$ENV_EXAMPLE" ]; then
    echo "[selfhost] ERROR: ${ENV_EXAMPLE} not found" >&2
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    echo "[selfhost] ${ENV_FILE} already exists — keeping the existing PRY_API_KEY."
else
    API_KEY="$(openssl rand -hex 24)"
    # The key is substituted into the copy only; the template keeps a
    # placeholder so no key is ever committed in either file.
    sed "s|^PRY_API_KEY=.*$|PRY_API_KEY=${API_KEY}|" "$ENV_EXAMPLE" >"$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "[selfhost] wrote ${ENV_FILE} with a generated PRY_API_KEY."
fi

cat <<'EOF'

Next:
  docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
    --env-file .env.selfhost up -d
  curl -s http://localhost:8002/health

Read the generated key with:
  grep '^PRY_API_KEY=' .env.selfhost

This profile publishes the API on 127.0.0.1:8002. Put a TLS reverse proxy
in front of it before exposing it to a network you do not control.
EOF
