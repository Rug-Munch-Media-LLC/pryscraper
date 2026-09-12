# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# Pry — Multi-stage Docker build (production-hardened)
#
#   * Pinned base image (digest) — reproducible builds
#   * Stage 1 builds deps + Playwright + Tesseract; stage 2 is a slim runtime
#   * Runs as non-root user `pry` (uid 1000); /app is owned by pry
#   * HEALTHCHECK via curl against /health
#   * ENTRYPOINT handles SIGTERM/SIGINT and drains in-flight requests
#   * read_only rootfs-compatible: writable paths live under /app/pry-data
#     (named volume) and /tmp (tmpfs); Python bytecode writes are disabled;
#     Playwright browsers live at PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
#     (read-only shared location)

# Stage 1: Build deps + Playwright + Tesseract
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget=1.25.0-2 \
    curl=8.14.1-2+deb13u5 \
    gnupg=2.4.7-21+deb13u1 \
    ca-certificates=20250419 \
    libnss3=2:3.110-1+deb13u4 \
    libnspr4=2:4.36-1 \
    libatk1.0-0t64=2.56.2-1+deb13u2 \
    libatk-bridge2.0-0t64=2.56.2-1+deb13u2 \
    libcups2t64=2.4.10-3+deb13u2 \
    libdrm2=2.4.124-2 \
    libdbus-1-3=1.16.2-2 \
    libxcb1=1.17.0-2+b1 \
    libxkbcommon0=1.7.0-2 \
    libxcomposite1=1:0.4.6-1 \
    libxdamage1=1:1.1.6-1+b2 \
    libxrandr2=2:1.5.4-1+b3 \
    libgbm1=25.0.7-2+deb13u1 \
    libpango-1.0-0=1.56.3-1 \
    libcairo2=1.18.4-1+b1 \
    libasound2t64=1.2.14-1+deb13u1 \
    tesseract-ocr=5.5.0-1+b1 \
    tesseract-ocr-eng=1:4.1.0-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Install the fully pinned lock (reproducible builds). requirements.txt is
# only the loose range manifest from pyproject.toml — never an install source.
COPY requirements.docker.lock .
# Pre-filtered runtime lock (dev/test deps + git editables removed by
# scripts/gen-docker-lock.py; drift-checked in CI).
RUN pip install --no-cache-dir -r requirements.docker.lock
RUN python3 -m playwright install chromium 2>&1 | tail -1

# Stage 2: Runtime
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Pry" \
      org.opencontainers.image.description="Pry open any website — web scraping + browser automation API" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Rug Munch Media LLC"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl=8.14.1-2+deb13u5 \
    ca-certificates=20250419 \
    libnss3=2:3.110-1+deb13u4 \
    libnspr4=2:4.36-1 \
    libatk1.0-0t64=2.56.2-1+deb13u2 \
    libatk-bridge2.0-0t64=2.56.2-1+deb13u2 \
    libcups2t64=2.4.10-3+deb13u2 \
    libdrm2=2.4.124-2 \
    libdbus-1-3=1.16.2-2 \
    libxcb1=1.17.0-2+b1 \
    libxkbcommon0=1.7.0-2 \
    libxcomposite1=1:0.4.6-1 \
    libxdamage1=1:1.1.6-1+b2 \
    libxrandr2=2:1.5.4-1+b3 \
    libgbm1=25.0.7-2+deb13u1 \
    libpango-1.0-0=1.56.3-1 \
    libcairo2=1.18.4-1+b1 \
    libasound2t64=1.2.14-1+deb13u1 \
    tesseract-ocr=5.5.0-1+b1 \
    tesseract-ocr-eng=1:4.1.0-2 \
    && rm -rf /var/lib/apt/lists/*

# Playwright browsers are copied to a shared, read-only location and pointed
# at via PLAYWRIGHT_BROWSERS_PATH. This keeps them out of $HOME (which is
# read-only under `read_only: true`) and works for the non-root `pry` user.
# config.json lives inside the data volume so runtime config changes persist
# and the root filesystem can stay read-only.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PRY_CONFIG_FILE=/app/pry-data/config.json

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/ms-playwright /ms-playwright

WORKDIR /app
# Copy the full app tree so every package ships (db/, x402/, billing/, data
# domains, routers, ...). The .dockerignore excludes tests/, *.md, caches,
# .env, and build files — this is the single source of truth for the image.
COPY . ./
# Install the src-layout pry package (entry points + importable pry.*)
RUN pip install --no-cache-dir --no-deps .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN mkdir -p /app/sessions /app/pry-data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-root runtime user. /app (and its writable subdirs) belong to pry.
# /ms-playwright stays root-owned: it is read-only at runtime (read_only
# rootfs) and pry only needs read access to the browser binaries.
RUN useradd --create-home --shell /bin/bash --uid 1000 pry \
    && chown -R pry:pry /app
USER pry

EXPOSE 8002

# docker-compose healthcheck uses the same probe. /health returns 200 only
# when the process is up (and FlareSolverr is reachable); the start_period
# absorbs the migration + warmup window.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-fsS", "http://localhost:8002/health"]

# SIGTERM lets the entrypoint drain in-flight requests before exit.
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "pry.api.api:app", "--host", "0.0.0.0", "--port", "8002", \
     "--workers", "1", "--timeout-keep-alive", "120", "--limit-concurrency", "20", \
     "--timeout-graceful-shutdown", "30"]
