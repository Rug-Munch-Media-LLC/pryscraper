"""kolscan.io leaderboard client (the only KOL-wallet site reachable this run).

Parses the Next.js RSC flight payload with a tolerant regex — no browser, no
auth, no evasion. One page, 2s minimum interval, 15 min cache.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from .models import KolAccount
from .wallets import claim_from_leaderboard

LEADERBOARD_URL = "https://kolscan.io/leaderboard"
MIN_INTERVAL_S = 2.0
CACHE_TTL_S = 900.0

_RECORD_RE = re.compile(
    r'"wallet_address":"(?P<wallet>[1-9A-HJ-NP-Za-km-z]{32,44})",'
    r'"name":"(?P<name>[^"]{0,80})",'
    r'"pfp":(?:null|"[^"]*"),'
    r'"telegram":(?P<tg>null|"[^"]*"),'
    r'"twitter":(?P<tw>null|"[^"]*")'
)
_HANDLE_RE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", re.I)


def _unescape(payload: str) -> str:
    return payload.replace('\\"', '"').replace("\\\\", "\\")


def _first(value: str) -> str:
    if not value or value == "null":
        return ""
    return value.strip('"')


def parse_leaderboard(
    html: str, evidence_url: str = LEADERBOARD_URL
) -> tuple[list[KolAccount], int]:
    """Return ``(accounts, wallet_only_rows)``. Never raises on partial HTML."""
    accounts: list[KolAccount] = []
    wallet_only = 0
    seen: set[str] = set()
    for match in _RECORD_RE.finditer(_unescape(html or "")):
        handle_match = _HANDLE_RE.search(_first(match.group("tw")))
        if handle_match is None:
            wallet_only += 1
            continue
        handle = handle_match.group(1)
        key = handle.casefold()
        if key in seen:
            continue
        seen.add(key)
        account = KolAccount(
            platform="x",
            handle=handle,
            display_name=_first(match.group("name")),
            telegram=_first(match.group("tg")),
            sources=["kolscan_leaderboard"],
            confidence=0.4,
        )
        try:
            account.wallets = [claim_from_leaderboard(match.group("wallet"), evidence_url, handle)]
        except ValueError:
            wallet_only += 1
        accounts.append(account)
    return accounts, wallet_only


@dataclass
class KolscanClient:
    """Bounded, cached, rate-limited fetch. ``http`` only needs ``.get``."""

    http: Any
    base_url: str = LEADERBOARD_URL
    min_interval: float = MIN_INTERVAL_S
    cache_ttl: float = CACHE_TTL_S
    clock: Callable[[], float] = time.monotonic
    user_agent: str = "RugMunchKOLBot/0.1 (+https://rugmunch.io/bot)"
    _last: float = field(default=-1e9, init=False)
    _cache: tuple[float, str] | None = field(default=None, init=False)

    def _body(self) -> str:
        now = self.clock()
        if self._cache is not None and now - self._cache[0] < self.cache_ttl:
            return self._cache[1]
        wait = self.min_interval - (now - self._last)
        if wait > 0 and self._last > -1e8:
            time.sleep(wait)
        response = self.http.get(self.base_url, headers={"User-Agent": self.user_agent})
        self._last = self.clock()
        status = getattr(response, "status_code", 0)
        if status != 200:
            raise RuntimeError(f"kolscan leaderboard returned HTTP {status}")
        text = getattr(response, "text", "")
        text = text() if callable(text) else text
        self._cache = (self._last, text)
        return text

    def fetch(self, limit: int = 50) -> tuple[list[KolAccount], int]:
        """Fetch and truncate. ``limit`` is a hard cap, not a hint."""
        accounts, wallet_only = parse_leaderboard(self._body(), self.base_url)
        return accounts[: max(0, limit)], wallet_only
