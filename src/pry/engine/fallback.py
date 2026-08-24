"""Pry — generic fallback-chain framework ("always retrieve the data").

Composes an ordered list of fetcher callables into one resilient lookup: try
each fetcher in order, return the first non-empty result, and only when every
fetcher fails fall back to the last result (or ``None`` / ``[]``). Fetchers
may be sync or async and may return ``None``, ``[]``, ``{}``, ``""`` (treated
as "no data") or any truthy payload. A fetcher may raise :class:`BlockedError`
to signal an anti-bot / access block (tracked separately from a generic
failure); any other exception is swallowed and recorded — the chain itself
never raises.

Status tracking mirrors the :mod:`sports_data.sources` health pattern: a
module-level registry records per-fetcher ``reachable`` / ``blocked`` /
``last_checked`` / ``latency_ms`` / ``error``, and :func:`fallback_status`
merges it with the fetcher roster for observability.

Public API:

* ``fetch_with_fallback(fetchers, *args, **kwargs)`` — run a chain.
* ``with_fallback(*fetchers)`` — compose fetchers into one resilient callable.
* ``fallback_status(fetchers=None)`` — per-fetcher health/status snapshot.
* ``BlockedError`` — raise from a fetcher to signal an access block.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)


class BlockedError(Exception):
    """Raised by a fetcher to signal an anti-bot / access block.

    A blocked attempt is tracked as ``blocked=True`` (distinct from a generic
    failure) but still lets the chain continue to the next fetcher.
    """


# ── Health tracking (mirrors sports_data/sources.py pattern) ────────────
# name -> {reachable, blocked, last_checked, latency_ms, error}
_HEALTH: dict[str, dict[str, Any]] = {}


def _mark(
    name: str,
    *,
    ok: bool,
    blocked: bool = False,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of the last attempt for one fetcher."""
    health = _HEALTH.setdefault(
        name,
        {
            "reachable": True,
            "blocked": False,
            "last_checked": None,
            "latency_ms": None,
            "error": None,
        },
    )
    health["reachable"] = ok and not blocked
    health["blocked"] = bool(blocked)
    health["last_checked"] = datetime.now(UTC).isoformat() + "Z"
    if latency_ms is not None:
        health["latency_ms"] = int(latency_ms)
    if error is not None:
        health["error"] = str(error)


def reset_status() -> None:
    """Drop all recorded per-fetcher health (tests / maintenance)."""
    _HEALTH.clear()


def _name_of(fetcher: Callable[..., Any], index: int) -> str:
    """Stable label for a fetcher: ``__name__``, deduped with the index."""
    base = getattr(fetcher, "__name__", None) or type(fetcher).__name__ or "fetcher"
    return f"{base}:{index}"


def fallback_status(
    fetchers: Sequence[Callable[..., Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-fetcher health snapshot, merged from the attempt registry.

    Args:
        fetchers: Optional roster of fetchers to report (resolved by label).
            ``None`` reports every fetcher that has attempted at least once.

    Returns:
        Mapping of fetcher label -> ``{name, reachable, blocked, last_checked,
        latency_ms, error, status}`` where ``status`` is ``"untried"``,
        ``"success"``, ``"blocked"`` or ``"failed"``. Never raises.
    """
    names: list[str] = (
        list(_HEALTH) if fetchers is None else [_name_of(f, i) for i, f in enumerate(fetchers)]
    )
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        health = dict(_HEALTH.get(name, {}))
        status = "untried"
        if health.get("last_checked") is not None:
            if health.get("blocked"):
                status = "blocked"
            elif health.get("reachable"):
                status = "success"
            else:
                status = "failed"
        out[name] = {
            "name": name,
            "reachable": health.get("reachable", True),
            "blocked": health.get("blocked", False),
            "last_checked": health.get("last_checked"),
            "latency_ms": health.get("latency_ms"),
            "error": health.get("error"),
            "status": status,
        }
    return out


# ── Chain runner ────────────────────────────────────────────────────────
def _is_empty(value: Any) -> bool:
    """True when a fetcher result carries no data (None / [] / {} / "" / 0)."""
    return not value


async def _maybe_await(result: Any) -> Any:
    """Await a coroutine/awaitable result; pass everything else through."""
    if inspect.isawaitable(result):
        return await result
    return result


async def fetch_with_fallback(
    fetchers: list[Callable[..., Any]] | Sequence[Callable[..., Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Try each fetcher in order; return the first non-empty result.

    Args:
        fetchers: Ordered fetchers. Each is called as ``fetcher(*args,
            **kwargs)``; a coroutine/awaitable return value is awaited.
            A truthy result short-circuits the chain and is returned. A
            falsy result (``None`` / ``[]`` / ``{}`` / ``""`` / ``0``) is
            treated as "no data" and the chain moves on.
        *args / **kwargs: Forwarded verbatim to every fetcher.

    Returns:
        The first non-empty result; when every fetcher fails, the last
        result (which may be ``None`` / ``[]`` / ``{}``). Returns ``None``
        for an empty fetcher list. Never raises.
    """
    if not fetchers:
        return None
    last_result: Any = None
    for index, fetcher in enumerate(fetchers):
        name = _name_of(fetcher, index)
        start = time.monotonic()
        try:
            result = await _maybe_await(fetcher(*args, **kwargs))
            latency_ms = int((time.monotonic() - start) * 1000)
            if _is_empty(result):
                _mark(name, ok=False, latency_ms=latency_ms, error="empty result")
                last_result = result
                continue
            _mark(name, ok=True, latency_ms=latency_ms)
            return result
        except BlockedError as exc:  # access block — flag, keep trying
            latency_ms = int((time.monotonic() - start) * 1000)
            _mark(
                name,
                ok=False,
                blocked=True,
                latency_ms=latency_ms,
                error=str(exc) or "blocked",
            )
            logger.warning("fallback_fetcher_blocked", extra={"fetcher": name})
            last_result = None
            continue
        except Exception as exc:  # noqa: BLE001 - chain contract: never raise
            latency_ms = int((time.monotonic() - start) * 1000)
            _mark(name, ok=False, latency_ms=latency_ms, error=str(exc) or type(exc).__name__)
            logger.warning("fallback_fetcher_failed", extra={"fetcher": name, "error": str(exc)})
            last_result = None
            continue
    return last_result


def with_fallback(*fetchers: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Compose fetchers into one resilient async function.

    The returned callable forwards ``*args`` / ``**kwargs`` to
    :func:`fetch_with_fallback` and returns its result (first non-empty
    result, or the last result when every fetcher fails). Never raises.

    Example:
        >>> fetch_price = with_fallback(fetch_primary, fetch_secondary)
        >>> price = await fetch_price("BTC-USD")
    """

    async def _composed(*args: Any, **kwargs: Any) -> Any:
        return await fetch_with_fallback(list(fetchers), *args, **kwargs)

    return _composed


__all__ = [
    "BlockedError",
    "fallback_status",
    "fetch_with_fallback",
    "reset_status",
    "with_fallback",
]
