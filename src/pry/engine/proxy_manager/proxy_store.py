"""Owner-only credential, config and health persistence for proxies.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pry.engine.proxy_manager.proxy_types import (
    CREDENTIALS_MODE,
    ProxyConfig,
    redact_credentials,
)

logger = logging.getLogger(__name__)


def _os_module() -> Any:
    """Resolve ``os`` via the package facade (the seam existing tests patch)."""
    from pry.engine import proxy_manager

    return getattr(proxy_manager, "os", os)


def harden_file(path: Path) -> bool:
    """Force ``0600`` on a secret file; refuse it if that cannot be done.

    Returns True when the file is absent or owner-only afterwards. A
    group/world-readable file is chmod'ed on first touch (self-healing);
    if the chmod fails we return False so the caller refuses to load it.
    """
    os_mod = _os_module()
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return True  # absent -> nothing to protect
    if mode & 0o077 == 0:
        return True
    logger.warning(
        "proxy_secret_permissions_loose",
        extra={"path": str(path), "mode": oct(mode)},
    )
    try:
        os_mod.chmod(path, CREDENTIALS_MODE)
        mode = path.stat().st_mode & 0o777
    except OSError as e:
        logger.error(
            "proxy_secret_permissions_unfixable",
            extra={"path": str(path), "error": redact_credentials(str(e))[:120]},
        )
        return False
    if mode & 0o077:
        logger.error(
            "proxy_secret_permissions_refused",
            extra={"path": str(path), "mode": oct(mode)},
        )
        return False
    return True


def write_secret_file(path: Path, payload: str) -> None:
    """Write a secrets file owner-only (0600) and re-assert the mode."""
    os_mod = _os_module()
    try:
        path.write_text(payload)
        os_mod.chmod(path, CREDENTIALS_MODE)
        if path.stat().st_mode & 0o077:
            logger.error("proxy_secret_write_not_private", extra={"path": str(path)})
    except OSError as e:
        logger.debug(
            "proxy_secret_write_failed",
            extra={"error": redact_credentials(str(e))[:80]},
        )


def load_config_file(path: Path) -> ProxyConfig:
    """Load the active config, refusing a file with loose permissions."""
    if not path.exists():
        return ProxyConfig()
    if not harden_file(path):
        logger.error("proxy_config_refused_insecure_permissions")
        return ProxyConfig()
    try:
        return ProxyConfig(**json.loads(path.read_text()))
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("proxy_state_load_failed", extra={"error": str(e)[:160]})
    return ProxyConfig()


def load_credential_file(path: Path) -> dict[str, ProxyConfig]:
    """Load stored credential entries, refusing a loosely-permissioned file."""
    if not path.exists():
        return {}
    if not harden_file(path):
        logger.error("proxy_credentials_refused_insecure_permissions")
        return {}
    try:
        data = json.loads(path.read_text())
        return {k: ProxyConfig(**v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "proxy_state_load_failed",
            extra={"error": redact_credentials(str(e))[:160]},
        )
    return {}


class ProxyStoreMixin:
    """File-backed config/credential/health persistence for :class:`ProxyManager`."""

    def _harden_file(self, path: Path) -> bool:
        return harden_file(path)

    def _write_secret_file(self, path: Path, payload: str) -> None:
        write_secret_file(path, payload)

    def _load_config(self) -> ProxyConfig:
        return load_config_file(self.config_file)

    def _load_credentials(self) -> dict[str, ProxyConfig]:
        return load_credential_file(self.creds_file)

    def _save_health(self) -> None:
        """Persist health state owner-only: keys are proxy URLs with credentials."""
        super()._save_health()
        try:
            _os_module().chmod(self.health_file, CREDENTIALS_MODE)
        except OSError as e:
            logger.debug("proxy_health_chmod_failed", extra={"error": str(e)[:80]})

    def _save_config(self) -> None:
        self._write_secret_file(self.config_file, json.dumps(self.active_config.__dict__, indent=2))

    def _save_credentials(self) -> None:
        data = {k: v.__dict__ for k, v in self.credentials.items()}
        self._write_secret_file(self.creds_file, json.dumps(data, indent=2, default=str))


__all__ = [
    "ProxyStoreMixin",
    "harden_file",
    "load_config_file",
    "load_credential_file",
    "write_secret_file",
]
