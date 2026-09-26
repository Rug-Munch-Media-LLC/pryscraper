"""Shared compose-render helpers for the self-host package tests.

The self-host profile (``docker-compose.selfhost.yml``) is an OVERLAY on
``docker-compose.yml``, not a replacement. Docker Compose merges two files
non-obviously: sequences (``ports``, ``volumes``, ``environment``) are
APPENDED or merged by key rather than replaced, and scalar overrides only work
per-key. Every assertion in this package exists because a plausible-looking
overlay silently produced the wrong runtime configuration in practice:

* ``ports`` merged instead of replaced  -> the self-host box ALSO published
  8005 and stole the operator's production port.
* ``env_file: !reset []`` did not clear the base file -> the self-host
  container inherited an absolute operator secrets path that does not exist
  on a laptop.
* the base's ``TOR_ENABLED=1`` / ``TOR_SOCKS5_HOST=tor`` survived the merge
  -> the ladder tried to dial a SOCKS5 proxy belonging to a service this
  profile deletes, and every scrape failed on connect timeout.

The merge is resolved by the real ``docker compose config`` (the only true
oracle) and asserted against its normalized output. Helpers skip the calling
test when the Docker CLI is unavailable rather than failing on a machine
without it.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

# tests/selfhost/conftest.py -> tests/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
SELFHOST_COMPOSE = REPO_ROOT / "docker-compose.selfhost.yml"
SELFHOST_ENV_EXAMPLE = REPO_ROOT / ".env.selfhost.example"

# Services the self-host profile must not boot: every one of them is either
# operator-only stateful infrastructure or a second copy of a helper service.
OPERATOR_ONLY_SERVICES = (
    "postgres",
    "redis",
    "prometheus",
    "grafana",
    "flaresolverr",
    "postgres-exporter",
    "redis-exporter",
    "blackbox-exporter",
    "otel-collector",
    "jaeger",
    "tor",
)


def docker_compose() -> list[str]:
    """Return a usable `docker compose` argv prefix, or skip the test."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI not available")
    probe = subprocess.run(  # noqa: S603 - argv is static, path resolved via which()
        [docker, "compose", "version"],
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("docker compose plugin not available")
    return [docker, "compose"]


def render_compose(*extra_env: str, with_selfhost: bool = True) -> dict[str, Any]:
    """Render the merged compose model via `docker compose config`."""
    files = ["-f", str(BASE_COMPOSE)]
    if with_selfhost:
        files += ["-f", str(SELFHOST_COMPOSE)]
    env = {**os.environ, "POSTGRES_PASSWORD": "t", "GRAFANA_PASSWORD": "t"}
    for item in extra_env:
        key, _, value = item.partition("=")
        env[key] = value
    proc = subprocess.run(  # noqa: S603 - argv built from repo paths + static flags
        [*docker_compose(), *files, "config", "--format", "json"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    assert proc.returncode == 0, f"compose config failed: {proc.stderr.decode()[:2000]}"
    return json.loads(proc.stdout)


def read_env_template(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE dotenv template, ignoring blanks and comments."""
    text = path.read_text(encoding="utf-8")
    pairs = [
        line.split("=", 1)
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ]
    return {k.strip(): v.strip() for k, v in pairs}
