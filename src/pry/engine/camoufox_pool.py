"""Process-level pooled Camoufox browser (launched once, reused across requests).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under BSL 1.1 — see LICENSE-BSL-STEALTH.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_pooled_camoufox: Any = None
_pooled_camoufox_config: dict[str, Any] | None = None


async def get_pooled(factory: Any, config: dict[str, Any]) -> Any:
    """Return the shared Camoufox browser, launching it once and caching it.

    A changed config closes the cached browser and relaunches with the new one.
    """
    global _pooled_camoufox, _pooled_camoufox_config
    if _pooled_camoufox is not None and _pooled_camoufox_config == config:
        return _pooled_camoufox
    if _pooled_camoufox is not None:
        try:
            await _pooled_camoufox.__aexit__(None, None, None)
        except Exception:
            logger.debug("browser_cleanup_failed", exc_info=True)
        _pooled_camoufox = None
    _pooled_camoufox = await factory(**config).__aenter__()
    _pooled_camoufox_config = config
    return _pooled_camoufox


async def close_pooled() -> None:
    """Close the pooled Camoufox browser (graceful shutdown)."""
    global _pooled_camoufox, _pooled_camoufox_config
    if _pooled_camoufox is not None:
        try:
            await _pooled_camoufox.__aexit__(None, None, None)
        except Exception:
            logger.debug("browser_cleanup_failed", exc_info=True)
        _pooled_camoufox = None
        _pooled_camoufox_config = None


__all__ = ["close_pooled", "get_pooled"]
