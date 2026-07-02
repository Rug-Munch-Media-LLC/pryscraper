"""Pry - centralized data-directory resolution.

Single source of truth for the on-disk data root. Override at runtime via
the PRY_DATA_DIR environment variable.

Examples:
  PRY_DATA_DIR=/var/lib/pry         # systemd / docker production
  PRY_DATA_DIR=/tmp/pry-test-$$     # CI scratch space

All other modules should import PRY_DATA_DIR (or use subdir(name)) instead
of hardcoding Path("~/.pry/x").

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
from pathlib import Path

# Single source of truth. Override with PRY_DATA_DIR env var.
PRY_DATA_DIR: Path = Path(os.getenv("PRY_DATA_DIR", "~/.pry")).expanduser().resolve()

# Known subdirectories. Not enforced - subdir() accepts any name - but
# useful for documentation and tooling that wants to enumerate them.
SUBDIRS: tuple[str, ...] = (
    "accounts",
    "actors",
    "agency",
    "commerce",
    "costing",
    "freshness",
    "gdpr",
    "gdpr_real",
    "intel",
    "jobs",
    "llm_usage",
    "monitors",
    "pipelines",
    "proxies",
    "quality",
    "referrals",
    "reports",
    "reports_real",
    "reviews",
    "seo",
    "sessions",
    "structure",
    "training",
    "vault",
    "webhooks",
    "x402",
)


def subdir(name: str) -> Path:
    """Get a subdirectory under PRY_DATA_DIR, creating it if needed.

    Use this in modules that write files: `from paths import subdir; d = subdir("quality")`.
    """
    path = PRY_DATA_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_data_dir() -> Path:
    """Ensure PRY_DATA_DIR itself exists. Returns the path.

    Call once at process startup if you want the root created eagerly
    (e.g., before any subdir access).
    """
    PRY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return PRY_DATA_DIR
