# syntax=docker/dockerfile:1.7
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# Pry — Multi-stage Docker build (production-hardened, size-optimised)
#
#   * Pinned base image (digest) — reproducible builds
#   * Stage 1 (builder) installs the pinned lock + Playwright browsers and
#     prunes everything the runtime never reads; stage 2 is a slim runtime that
#     only receives the finished artefacts — no compilers, no pip cache, no
#     bytecode, no package tests.
#   * ONE Chromium: Playwright's full build (`playwright install --no-shell`).
#     The distro `chromium` package (~380 MB) and the separate
#     `chromium-headless-shell` (~260 MB) are both duplicates of the same
#     engine and are deliberately absent. Every launch passes
#     `channel="chromium"` (pry.core.chromium) so headless and headed runs use
#     that single binary.
#   * Runs as non-root user `pry` (uid 1000); /app is owned by pry
#   * HEALTHCHECK via curl against /health
#   * ENTRYPOINT handles SIGTERM/SIGINT and drains in-flight requests
#   * read_only rootfs-compatible: writable paths live under /app/pry-data
#     (named volume) and /tmp (tmpfs); Python bytecode writes are disabled;
#     Playwright browsers live at PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
#     (read-only shared location)

# Stage 1: build the dependency tree, the browsers, and the wheel cache
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
# Install the fully pinned lock (reproducible builds). requirements.txt is
# only the loose range manifest from pyproject.toml — never an install source.
COPY requirements.docker.lock .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.docker.lock
# Optional scraping backends (camoufox anti-detection Firefox, curl_cffi TLS
# impersonation). The camoufox browser itself is fetched at first use into
# $HOME/.cache (now on the pry-data volume), not baked into the image.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile "camoufox>=0.4.0" "curl_cffi>=0.7.0"
# `--no-shell` skips chromium-headless-shell (~260 MB). The full build is the
# only browser the runtime needs; `channel="chromium"` selects it for headless.
RUN python -m playwright install --no-shell chromium

# Prune the build result so the COPY into the runtime carries only runtime
# bytes: no pip, no bytecode, no per-package test suites, no non-en locales.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip \
           /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
 && find /usr/local/lib/python3.12/site-packages -type d -name '__pycache__' -prune -exec rm -rf {} + \
 && find /usr/local/lib/python3.12/site-packages -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete \
 && find /usr/local/lib/python3.12/site-packages -maxdepth 2 -type d -name tests -prune -exec rm -rf {} + \
 && find /ms-playwright -type d -name locales -exec bash -c \
      'cd "$1" && find . -maxdepth 1 -type f ! -name "en-US.pak" -delete' _ {} \;

# Stage 2: Runtime
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Pry" \
      org.opencontainers.image.description="Pry open any website — web scraping + browser automation API" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Rug Munch Media LLC"

# One apt transaction, one layer. Two `apt-get update` layers duplicated the
# package metadata and the runtime toolchain, and every additional layer is
# permanent image size (nothing here is removed at runtime, so layer count ==
# bytes once it is pushed).
#
# Only the shared libraries Playwright's Chromium actually links against are
# installed — NOT the distro `chromium` package (which pulls a second 380 MB
# browser, GTK and a font stack). Fonts are explicit because screenshots and
# PDFs need real glyphs without the distro browser dragging them in.
#
# `postgresql-client` is pg_dump for the entrypoint's pre-migration backup
# guard. The pinned base digest is Debian 13 (trixie), which ships
# postgresql-client 17; a NEWER pg_dump can dump an OLDER server (compose runs
# postgres:16) — never the reverse. `docker-entrypoint.sh` still fails closed
# when PRY_REQUIRE_PRE_MIGRATION_BACKUP=1.
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 \
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-unifont \
    fonts-dejavu-core \
    tesseract-ocr \
    tesseract-ocr-eng \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* /usr/share/locale/*

# Playwright browsers are copied to a shared, read-only location and pointed
# at via PLAYWRIGHT_BROWSERS_PATH. This keeps them out of $HOME (which is
# read-only under `read_only: true`) and works for the non-root `pry` user.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PRY_CONFIG_FILE=/app/pry-data/config.json

# Only the pruned artefacts cross the stage boundary — the builder's apt/pip
# scratch and build context never become runtime layers.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /ms-playwright /ms-playwright

# Non-root runtime user created BEFORE the app tree, so `COPY --chown`
# applies ownership in the copy layer itself. The previous order (COPY, then
# `chown -R pry:pry /app`) rewrote every inode and duplicated the entire app
# tree into an extra layer — measured 284 MB of pure duplication.
RUN useradd --create-home --shell /bin/bash --uid 1000 pry

WORKDIR /app
# Copy the app tree so every package ships (db/, x402/, billing/, data
# domains, routers, ...). .dockerignore is the single source of truth for
# what is excluded (tests/, docs, datasets/, data/, website/, caches).
COPY --chown=pry:pry . ./
# Install the src-layout pry package (entry points + importable pry.*) as
# root: only site-packages is written, /app stays pry-owned.
RUN pip install --no-cache-dir --no-compile --no-deps . \
    && find /usr/local/lib/python3.12/site-packages -maxdepth 2 -type d -name '__pycache__' -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.12/site-packages -type f -name '*.pyc' -delete
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN mkdir -p /app/sessions /app/pry-data \
    && chmod 755 /usr/local/bin/docker-entrypoint.sh \
    && chown pry:pry /app/sessions /app/pry-data
# /ms-playwright stays root-owned: it is read-only at runtime (read_only
# rootfs) and pry only needs read access to the browser binaries.
USER pry

# 8002 = REST API (default CMD). 8006 = standalone Streamable HTTP MCP
# (`pry_mcp.asgi:app`, selectable via the compose `pry-mcp` service or
# `docker run --entrypoint uvicorn ... pry_mcp.asgi:app`).
EXPOSE 8002 8006

# docker-compose healthcheck uses the same probe. /health returns 200 only
# when BOTH critical deps (Redis + database) answer; FlareSolverr is reported
# but does not gate. The self-host overlay (no Redis) overrides this probe with
# /healthz. start_period absorbs the migration + warmup window.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-fsS", "http://localhost:8002/health"]

# SIGTERM lets the entrypoint drain in-flight requests before exit.
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "pry.api.api:app", "--host", "0.0.0.0", "--port", "8002", \
     "--workers", "1", "--timeout-keep-alive", "120", "--limit-concurrency", "20", \
     "--timeout-graceful-shutdown", "30"]
