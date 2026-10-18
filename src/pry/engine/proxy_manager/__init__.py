"""Pry — Proxy Manager with affiliate-signup flow.

Health scoring/circuit-breaker lives in :mod:`pry.engine.proxy_health`; the
provider catalog lives in :mod:`pry.engine.proxy_providers`. This package owns
configuration, selection and the signup/referral flow, split by responsibility:

* :mod:`~pry.engine.proxy_manager.proxy_types` — config dataclass + redaction
* :mod:`~pry.engine.proxy_manager.proxy_store` — owner-only file persistence
* :mod:`~pry.engine.proxy_manager.proxy_rotation` — affinity/quarantine select
* :mod:`~pry.engine.proxy_manager.proxy_config` — provider/env/Webshare wiring
* :mod:`~pry.engine.proxy_manager.proxy_referrals` — affiliate signup flow

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import os as os  # re-exported: existing tests patch this seam
import threading
from pathlib import Path
from typing import Any

from pry.engine.proxy_health import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    COOLDOWN_SECONDS,
    HEALTH_WINDOW_SIZE,
    ProxyHealthMixin,
)
from pry.engine.proxy_manager.proxy_config import ProxyConfigMixin
from pry.engine.proxy_manager.proxy_referrals import ProxyReferralMixin
from pry.engine.proxy_manager.proxy_rotation import ProxyRotationMixin, reset_selection_rotation
from pry.engine.proxy_manager.proxy_store import ProxyStoreMixin
from pry.engine.proxy_manager.proxy_types import (
    CREDENTIALS_MODE,
    PROXY_DIR,
    ProxyConfig,
    redact_credentials,
)
from pry.engine.proxy_providers import FREE_PROXY_SOURCES, PREMIUM_PROXY_PROVIDERS

__all__ = [
    "CONSECUTIVE_FAILURE_THRESHOLD",
    "COOLDOWN_SECONDS",
    "CREDENTIALS_MODE",
    "FREE_PROXY_SOURCES",
    "HEALTH_WINDOW_SIZE",
    "PREMIUM_PROXY_PROVIDERS",
    "PROXY_DIR",
    "ProxyConfig",
    "ProxyManager",
    "redact_credentials",
    "reset_selection_rotation",
]


class ProxyManager(
    ProxyStoreMixin,
    ProxyConfigMixin,
    ProxyReferralMixin,
    ProxyRotationMixin,
    ProxyHealthMixin,
):
    """Manages proxy selection, free fallbacks, and premium signup flow."""

    # Tunable health params (per-instance so tests can shrink them).
    health_window_size = HEALTH_WINDOW_SIZE
    consecutive_failure_threshold = CONSECUTIVE_FAILURE_THRESHOLD
    cooldown_seconds = COOLDOWN_SECONDS

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or PROXY_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "active_config.json"
        self.creds_file = self.data_dir / "credentials.json"
        self.health_file = self.data_dir / "proxy_health.json"
        self.active_config = self._load_config()
        self.credentials: dict[str, ProxyConfig] = self._load_credentials()
        self._health_data: dict[str, Any] = self._load_health()
        self._harden_file(self.health_file)
        self._health_lock = threading.Lock()
        self.auto_configure_from_env()
