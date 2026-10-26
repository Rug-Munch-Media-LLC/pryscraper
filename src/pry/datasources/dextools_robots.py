# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""robots.txt evaluation for Dextools (strict, ``User-agent: *`` group only).

Captured 2026-10-26 from https://www.dextools.io/robots.txt (732 bytes).
Disallowed prefixes (verbatim, longest-match wins):

    /app/user            /app/max-tabs-error   /stage   /demo
    /widget-chart/       /widget-bot/
    /api/core/pool/snipers/            /api/core/pool/candles/
    /api/core/pool/listing/token-race  /api/core/token/audits/
    /api/core/token/listings/social-network-updates/
    /api/core/news-feeds/              /api/core/votes/
    /api/core/chart-events/            /api/core/blockchain/listing/stats
    /api/core/search/pool              /api/auth/
    /shared/timeseries/mempool/
    /api-stage/                        /api-dev/

Everything else is allowed for ``*``; notably ``/app/<chain>/pair-explorer/<addr>``
is allowed, which is why this datasource reads rendered web pages instead of the
disallowed ``/api/core/search/pool`` endpoint.
"""

from __future__ import annotations

from pry.datasources.dextools_types import Refusal

#: Fallback when the live robots.txt cannot be parsed (conservative, captured copy).
FALLBACK_ROBOTS = """User-agent: *

Disallow: /app/user
Disallow: /app/max-tabs-error
Disallow: /stage
Disallow: /demo
Disallow: /widget-chart/
Disallow: /widget-bot/
Disallow: /api/core/pool/snipers/
Disallow: /api/core/pool/candles/
Disallow: /api/core/pool/listing/token-race
Disallow: /api/core/token/audits/
Disallow: /api/core/token/listings/social-network-updates/
Disallow: /api/core/news-feeds/
Disallow: /api/core/votes/
Disallow: /api/core/chart-events/
Disallow: /api/core/blockchain/listing/stats
Disallow: /api/core/search/pool
Disallow: /api/auth/
Disallow: /shared/timeseries/mempool/
Disallow: /api-stage/
Disallow: /api-dev/
"""


def _rules(text: str) -> list[str]:
    """Disallow rules of the ``User-agent: *`` group, in file order."""
    rules: list[str] = []
    in_star = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key.lower() == "user-agent":
            in_star = value == "*"
        elif key.lower() == "disallow" and in_star and value:
            rules.append(value)
    return rules


def robots_verdict(path: str, robots_text: str | None = None) -> Refusal | None:
    """Return a ``blocked.robots`` refusal if ``path`` is disallowed, else ``None``.

    Longest matching rule wins (RFC 9309). ``path`` may be a full URL or a path.
    """
    from urllib.parse import urlsplit

    target = urlsplit(path).path if "://" in path else path
    rules = _rules(robots_text if robots_text is not None else FALLBACK_ROBOTS)
    hits = [rule for rule in rules if target.startswith(rule)]
    if not hits:
        return None
    rule = max(hits, key=len)
    return Refusal(
        code="blocked.robots",
        reason=f"robots.txt disallows {rule!r} for User-agent: *",
        detail=target,
    )
