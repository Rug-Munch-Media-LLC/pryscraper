"""Pry — site capability registry.

``SiteCatalog`` is the single source of truth for "how we scrape each site":
a validated, look-up-able index over the static catalog in
``site_catalog.domains``. Every entry records the scrape method, expected
confidence, anti-bot posture, robots posture, latency budget, output schema
and key requirement BEFORE a tool is called, so callers can decide method +
expectations up-front instead of guessing at scrape time.

Public API:

* ``SiteCatalog()``          — validated index (raises ValueError on bad data)
* ``coverage()``             — full catalog as a list of dicts
* ``get_site(site_id)``      — one entry by id, or None
* ``recommend_method(url_or_domain)`` — best-known method + confidence for a
  target, or ``GENERIC_FALLBACK`` (``{method: "generic", confidence: 0.4}``)
  when the target is unknown.
* ``fallback_for(site_id)``  — ordered fallback chain of other site_ids to try
  when a site fails (module-level helper + ``SiteCatalog.fallback_for``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from site_catalog.domains import CATALOG

# Method vocabulary used across Pry. A method field may be a single token or a
# "+"-joined compound (e.g. "stealth+next_data") describing the fetch +
# parse pipeline a site actually needs.
METHOD_VOCABULARY: frozenset[str] = frozenset(
    {
        "api",
        "direct",
        "next_data",
        "embedded_json",
        "stealth",
        "stealth_browser",
        "browser",
        "tor",
        "proxy",
        "signed",
        "rsc",
    }
)

ANTI_BOT_LEVELS: frozenset[str] = frozenset({"none", "low", "medium", "high"})
ROBOTS_STATES: frozenset[str] = frozenset({"allowed", "restricted", "unknown", "blocked"})

DATA_DOMAINS: frozenset[str] = frozenset(
    {
        "crypto",
        "marketplace",
        "legal",
        "real-estate",
        "jobs",
        "travel",
        "attention",
        "local",
        "gov",
        "ip",
        "document",
        "browser",
    }
)

# Fallback returned by recommend_method() for unknown domains.
GENERIC_FALLBACK: dict[str, Any] = {"method": "generic", "confidence": 0.4}

_REQUIRED_KEYS: tuple[str, ...] = (
    "site_id",
    "domain",
    "method",
    "confidence",
    "anti_bot",
    "robots",
    "latency_ms_estimate",
    "output_schema",
    "requires_key",
    "data_domain",
    "fallback_chain",
    "tested",
)


def _normalize_host(value: str) -> str:
    """Strip scheme, path, port and ``www.`` from a host-ish string."""
    host = value.strip().lower()
    if "://" in host:
        host = urlsplit(host).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _entry_host(entry: dict[str, Any]) -> str:
    """Host part of an entry domain (drops any path prefix)."""
    domain = entry["domain"]
    return _normalize_host(domain.split("/", 1)[0])


def _entry_path(entry: dict[str, Any]) -> str:
    """Path prefix of an entry domain ("" when the domain is host-only)."""
    domain = entry["domain"]
    if "/" not in domain:
        return ""
    path = domain.split("/", 1)[1]
    return "/" + path.rstrip("/")


class SiteCatalog:
    """Validated index over the static site catalog."""

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self._entries = [dict(e) for e in (entries if entries is not None else CATALOG)]
        self._by_id: dict[str, dict[str, Any]] = {}
        self._validate()
        self._by_id = {e["site_id"]: e for e in self._entries}

    # ── validation ────────────────────────────────────────────────────────
    def _validate(self) -> None:
        seen: set[str] = set()
        for entry in self._entries:
            missing = [k for k in _REQUIRED_KEYS if k not in entry]
            if missing:
                raise ValueError(f"site_catalog entry missing keys: {missing}")
            site_id = entry["site_id"]
            if site_id in seen:
                raise ValueError(f"duplicate site_id in catalog: {site_id!r}")
            seen.add(site_id)
            for token in entry["method"].split("+"):
                if token not in METHOD_VOCABULARY:
                    raise ValueError(
                        f"site {site_id!r}: unknown method token {token!r} "
                        f"(vocabulary: {sorted(METHOD_VOCABULARY)})"
                    )
            confidence = entry["confidence"]
            if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
                raise ValueError(f"site {site_id!r}: confidence must be within 0-1")
            if entry["anti_bot"] not in ANTI_BOT_LEVELS:
                raise ValueError(f"site {site_id!r}: invalid anti_bot {entry['anti_bot']!r}")
            if entry["robots"] not in ROBOTS_STATES:
                raise ValueError(f"site {site_id!r}: invalid robots {entry['robots']!r}")
            latency = entry["latency_ms_estimate"]
            if not isinstance(latency, (int, float)) or float(latency) < 0:
                raise ValueError(f"site {site_id!r}: latency_ms_estimate must be >= 0")
            if not isinstance(entry["requires_key"], bool):
                raise ValueError(f"site {site_id!r}: requires_key must be bool")
            if not entry["output_schema"] or not all(
                isinstance(k, str) and k for k in entry["output_schema"]
            ):
                raise ValueError(
                    f"site {site_id!r}: output_schema must be a non-empty list of names"
                )
            if entry["data_domain"] not in DATA_DOMAINS:
                raise ValueError(f"site {site_id!r}: unknown data_domain {entry['data_domain']!r}")
            chain = entry["fallback_chain"]
            if not isinstance(chain, list) or not all(isinstance(s, str) and s for s in chain):
                raise ValueError(
                    f"site {site_id!r}: fallback_chain must be a list of site_id strings"
                )
            if not isinstance(entry["tested"], bool):
                raise ValueError(f"site {site_id!r}: tested must be bool")

    # ── public API ─────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._entries)

    def coverage(self) -> list[dict[str, Any]]:
        """Full catalog as a list of dicts (defensive copies)."""
        return [dict(e) for e in self._entries]

    def get_site(self, site_id: str) -> dict[str, Any] | None:
        """Return one entry by ``site_id``, or None when unknown."""
        entry = self._by_id.get(site_id)
        return dict(entry) if entry is not None else None

    def fallback_for(self, site_id: str) -> list[str]:
        """Ordered fallback chain of site_ids to try when ``site_id`` fails.

        Returns the entry's ``fallback_chain`` verbatim; ``[]`` when the site
        is unknown or has no declared fallbacks. Never raises.
        """
        entry = self._by_id.get(site_id)
        if entry is None:
            return []
        chain = entry.get("fallback_chain") or []
        return [s for s in chain if isinstance(s, str)]

    def recommend_method(self, url_or_domain: str) -> dict[str, Any]:
        """Best-known method + confidence for a URL or domain.

        Matching is host-based with path-prefix awareness (so
        ``https://www.google.com/travel/flights`` resolves to ``google_flights``,
        not ``google_maps``) and supports subdomains. Unknown targets return
        ``GENERIC_FALLBACK``.
        """
        target = (url_or_domain or "").strip().lower()
        if not target:
            return dict(GENERIC_FALLBACK)

        # A bare site_id is a valid lookup key too.
        direct = self._by_id.get(target)
        if direct is not None:
            return dict(direct)

        try:
            split = urlsplit(target if "://" in target else f"//{target}")
            host = _normalize_host(split.hostname or target)
            path = (split.path or "").rstrip("/")
        except ValueError:
            return dict(GENERIC_FALLBACK)

        if not host:
            return dict(GENERIC_FALLBACK)

        candidates: list[dict[str, Any]] = []
        for entry in self._entries:
            entry_host = _entry_host(entry)
            entry_path = _entry_path(entry)
            if entry_host != host and not host.endswith("." + entry_host):
                continue
            if entry_path and not path.startswith(entry_path):
                continue
            candidates.append(entry)

        if not candidates:
            return dict(GENERIC_FALLBACK)

        # Rank: exact host match first, then path specificity (host-only
        # entries win for path-less targets), then best confidence — so
        # https://www.google.com/travel/flights resolves to google_flights
        # and not to a generic google entry.
        def _score(entry: dict[str, Any]) -> tuple[int, int, float]:
            exact_host = 1 if _entry_host(entry) == host else 0
            path_specificity = len(_entry_path(entry))
            return (exact_host, path_specificity, float(entry["confidence"]))

        best = max(candidates, key=_score)
        return dict(best)


# Default catalog instance shared by the module-level fallback_for() helper.
_DEFAULT_CATALOG: SiteCatalog | None = None


def _default_catalog() -> SiteCatalog:
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = SiteCatalog()
    return _DEFAULT_CATALOG


def fallback_for(site_id: str) -> list[str]:
    """Ordered fallback chain of site_ids to try when ``site_id`` fails.

    Thin wrapper over :meth:`SiteCatalog.fallback_for` using the default
    catalog instance. Returns ``[]`` for unknown sites or sites with no
    declared fallbacks. Never raises.
    """
    return _default_catalog().fallback_for(site_id)
