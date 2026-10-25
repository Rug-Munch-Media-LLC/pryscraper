"""Source inventory + robots gate.

Nothing here invents data: a source is either ``reachable`` (we fetched it and
recorded the URL), ``blocked`` (with the machine-readable reason), or
``unverified`` (declared by a prior lane, not re-probed by us).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

USER_AGENT = "RugMunchKOLBot/0.1 (+https://rugmunch.io/bot)"

REACHABLE = "reachable"
BLOCKED = "blocked"
INTERFACE = "interface"  # a cross-lane import, not an HTTP fetch


@dataclass(frozen=True)
class SourceProbe:
    name: str
    url: str
    status: str
    http_status: int
    detail: str
    verification: str = "probed"  # probed | prior_record
    fetched_at: str = "2026-10-25"
    yields: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status == REACHABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "detail": self.detail,
            "verification": self.verification,
            "fetched_at": self.fetched_at,
            "yields": list(self.yields),
        }


#: Measured 2026-10-25 from Talos with USER_AGENT. See docs/KOL-DISCOVERY.md.
LIVE_PROBES: tuple[SourceProbe, ...] = (
    SourceProbe(
        name="x_profile_bio",
        url="https://x.com/cobie",
        status=BLOCKED,
        http_status=200,
        detail="robots.txt User-agent:* Disallow:/ (Crawl-delay 1) — HTML does carry "
        "og:title/og:description, but we do not crawl a disallowed path; the "
        "authenticated capture client is owned by the x-social-ops lane",
        yields=["bio_truncated_og"],
    ),
    SourceProbe(
        name="kolscan_leaderboard",
        url="https://kolscan.io/leaderboard",
        status=REACHABLE,
        http_status=200,
        detail="Next.js RSC flight payload parsed without a browser; "
        "robots.txt 404 (no crawl rules) -> self-imposed 2s rate limit",
        yields=["wallet_address", "twitter", "name", "telegram"],
    ),
    SourceProbe(
        name="kaito",
        url="https://kaito.ai/",
        status=BLOCKED,
        http_status=403,
        detail="edge WAF rejects non-browser clients; JS-rendered app, no public JSON",
    ),
    SourceProbe(
        name="dexcheck",
        url="https://dexcheck.io/",
        status=BLOCKED,
        http_status=403,
        detail="Cloudflare bot management; KOL board needs a JS-capable solver",
    ),
    SourceProbe(
        name="gmgn_leaderboard",
        url="https://gmgn.ai/leaderboard",
        status=BLOCKED,
        http_status=403,
        detail="Cloudflare; matches the x-social-ops stub (crypto_market/kol_leaderboards.py)",
    ),
    SourceProbe(
        name="cielo_finance",
        url="https://www.cielo.finance/",
        status=BLOCKED,
        http_status=0,
        detail="no response (curl exit: connection/TLS failure) — DNS or egress blocked",
    ),
    SourceProbe(
        name="dexscreener_smart_money",
        url="https://dexscreener.com/smart-money",
        status=BLOCKED,
        http_status=403,
        detail="Cloudflare per x-social-ops record; not re-probed in this run",
        verification="prior_record",
    ),
    SourceProbe(
        name="x_social_ops_bio_feed",
        url="import:crypto_market.kol_leaderboards (owner: x-social-ops lane)",
        status=INTERFACE,
        http_status=0,
        detail="cross-lane interface — consumed via import when the module is present, "
        "never re-implemented and never written to",
        verification="probed",
        yields=["kolscan_leaderboard"],
    ),
)


def _compile(pattern: str) -> re.Pattern[str]:
    """RFC 9309 subset: only ``*`` and a trailing ``$`` are metacharacters."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(f"^{regex}{'$' if anchored else ''}")


def _groups(robots_txt: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in (robots_txt or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        lowered = key.casefold()
        if lowered == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.casefold())
        elif lowered in {"allow", "disallow"} and agents:
            rules.append((lowered, value))
    if agents:
        groups.append((agents, rules))
    return groups


def _matches(rules: list[tuple[str, str]], path: str) -> bool:
    """Longest match wins; ``allow`` wins ties (RFC 9309 §2.2.2)."""
    best_len, best_verdict = -1, True
    for kind, pattern in rules:
        if not pattern:
            continue  # an empty Disallow means "allow everything"
        if _compile(pattern).match(path):
            verdict = kind == "allow"
            if len(pattern) > best_len or (len(pattern) == best_len and verdict):
                best_len, best_verdict = len(pattern), verdict
    return best_verdict


def robots_allows(robots_txt: str, path: str, user_agent: str = USER_AGENT) -> bool:
    """Conservative robots decision for one path."""
    token = user_agent.split("/", 1)[0].casefold()
    groups = _groups(robots_txt)
    named = [
        rules for agents, rules in groups if any(a and a != "*" and a in token for a in agents)
    ]
    if named:
        return _matches(named[0], path)
    wildcard = [rules for agents, rules in groups if "*" in agents]
    if wildcard:
        return _matches(wildcard[0], path)
    return True


def source_rows(
    probes: tuple[SourceProbe, ...] = LIVE_PROBES,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """JSON-ready source inventory plus a reachable/blocked/interface tally."""
    rows = [probe.to_dict() for probe in probes]
    reachable = sum(1 for row in rows if row["status"] == REACHABLE)
    interfaces = sum(1 for row in rows if row["status"] == INTERFACE)
    tally = {
        "total": len(rows),
        "reachable": reachable,
        "blocked": len(rows) - reachable - interfaces,
        "interfaces": interfaces,
    }
    return rows, tally
