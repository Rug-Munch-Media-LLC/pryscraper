"""Domain intelligence — RDAP WHOIS + crt.sh certificate transparency.

Both sources are free and keyless:

* RDAP (https://rdap.org/domain/{domain}) — the modern replacement for
  WHOIS. rdap.org bootstraps the request to the correct registry RIR and
  redirects; ``follow_redirects`` handles that transparently.
* crt.sh (https://crt.sh/?q=%25.{domain}&output=json) — Certificate
  Transparency log search; returns every certificate ever issued for a
  domain, including historical and subdomain entries.

Contract
--------
* :func:`whois_lookup` — async, never raises, returns a ``dict`` (``{}``
  on failure). Registration/expiration dates, registrar, status codes and
  nameservers for a domain.
* :func:`cert_transparency` — async, never raises, returns a ``list``
  (``[]`` on failure). Certificates issued for a domain.

Result shapes
-------------
``whois_lookup`` returns::

    {
        "domain": "example.com",
        "registrar": "RESERVED-Internet Assigned Numbers Authority",
        "created": "1992-01-01T00:00:00Z",
        "expires": "2027-01-01T00:00:00Z",
        "status": ["client delete prohibited", "client transfer prohibited"],
        "nameservers": ["a.iana-servers.net", "b.iana-servers.net"],
        "source": "rdap",
    }

``cert_transparency`` returns a list of::

    {
        "domain": "example.com",
        "issuer": "C=US, O=Let's Encrypt, CN=R11",
        "not_before": "2026-01-01T00:00:00",
        "not_after": "2026-04-01T00:00:00",
        "id": 1234567890,
        "source": "crt_sh",
    }

Free-API terms: rdap.org is open/CC0; crt.sh is free and unauthenticated
but can be slow — the timeout is set higher for it. Backoff: 2 retries,
exponential (0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_RDAP_ROOT = "https://rdap.org/domain"
_CRTSH_ROOT = "https://crt.sh"
_TIMEOUT = httpx.Timeout(20.0)
_CRTSH_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-research/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json, application/rdap+json",
}
_MAX_LIMIT = 100


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _event_date(events: Any, action: str) -> str | None:
    """Return the ``eventDate`` for an RDAP event action, or None."""
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        if _as_text(event.get("eventAction")) == action:
            return _as_text(event.get("eventDate"))
    return None


def _registrar_name(entities: Any) -> str | None:
    """Extract the registrar FN from RDAP ``entities`` (vCard array)."""
    if not isinstance(entities, list):
        return None
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        roles = entity.get("roles")
        if isinstance(roles, list) and "registrar" in roles:
            vcard = entity.get("vcardArray")
            if isinstance(vcard, list) and len(vcard) >= 2 and isinstance(vcard[1], list):
                for field in vcard[1]:
                    if isinstance(field, list) and len(field) >= 4 and field[0] == "fn":
                        return _as_text(field[3])
    return None


def _nameservers(ns_list: Any) -> list[str]:
    """Extract nameserver hostnames from RDAP ``nameservers``."""
    if not isinstance(ns_list, list):
        return []
    names: list[str] = []
    for ns in ns_list:
        if not isinstance(ns, dict):
            continue
        name = _as_text(ns.get("ldhName")) or _as_text(ns.get("unicodeName"))
        if name and name not in names:
            names.append(name)
    return names


def _map_rdap(raw: dict[str, Any], domain: str) -> dict[str, Any]:
    """Map an RDAP domain object onto the canonical record."""
    return {
        "domain": _as_text(raw.get("ldhName")) or domain.strip().lower(),
        "registrar": _registrar_name(raw.get("entities")),
        "created": _event_date(raw.get("events"), "registration"),
        "expires": _event_date(raw.get("events"), "expiration"),
        "status": [s for s in raw.get("status", []) if isinstance(s, str)],
        "nameservers": _nameservers(raw.get("nameservers")),
        "source": "rdap",
    }


def _map_cert(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one crt.sh JSON entry onto the canonical cert record."""
    name_value = _as_text(raw.get("name_value")) or _as_text(raw.get("common_name"))
    if name_value and "\n" in name_value:
        name_value = name_value.split("\n", 1)[0].strip()
    return {
        "domain": name_value,
        "issuer": _as_text(raw.get("issuer_name")),
        "not_before": _as_text(raw.get("not_before")),
        "not_after": _as_text(raw.get("not_after")),
        "id": raw.get("id") if isinstance(raw.get("id"), int) else None,
        "source": "crt_sh",
    }


async def _get_json(
    url: str, params: dict[str, str] | None = None, request_timeout: httpx.Timeout | None = None
) -> Any:
    """GET ``url`` and return parsed JSON (any shape), or None on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=request_timeout or _TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _valid_domain(domain: str) -> bool:
    """Basic sanity check: no spaces/slashes, at least one dot."""
    text = (domain or "").strip().lower()
    return bool(text) and "." in text and " " not in text and "/" not in text


# ── Public API ─────────────────────────────────────────────────────────
async def whois_lookup(domain: str) -> dict[str, Any]:
    """Look up registration data for a domain via RDAP.

    Args:
        domain: Domain name (e.g. ``"example.com"``).

    Returns:
        Domain record (see module docstring) or ``{}`` on failure
        (unregistered domain, network error, bad payload). Never raises.
    """
    try:
        return await _whois_lookup(domain)
    except Exception:
        logger.exception("rdap_whois_crashed", extra={"domain": domain})
        return {}


async def _whois_lookup(domain: str) -> dict[str, Any]:
    if not _valid_domain(domain):
        return {}
    payload = await _get_json(f"{_RDAP_ROOT}/{domain.strip().lower()}")
    if not isinstance(payload, dict):
        return {}
    return _map_rdap(payload, domain)


async def cert_transparency(domain: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return certificates issued for a domain from Certificate Transparency.

    Args:
        domain: Domain name (e.g. ``"example.com"``) — matches the domain
            and all subdomains.
        limit: Max certificate records to return (1-100).

    Returns:
        List of certificate records (see module docstring). ``[]`` on
        failure (no certs, network error, malformed payload). Never raises.
    """
    try:
        return await _cert_transparency(domain, limit)
    except Exception:
        logger.exception("crtsh_cert_search_crashed", extra={"domain": domain})
        return []


async def _cert_transparency(domain: str, limit: int) -> list[dict[str, Any]]:
    if not _valid_domain(domain):
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    # crt.sh's q parameter uses SQL LIKE wildcards: "%.example.com" matches
    # the domain and every subdomain. httpx percent-encodes the "%".
    payload = await _get_json(
        f"{_CRTSH_ROOT}/",
        {"q": f"%.{domain.strip().lower()}", "output": "json"},
        request_timeout=_CRTSH_TIMEOUT,
    )
    if not isinstance(payload, list):
        return []
    records = [_map_cert(raw) for raw in payload if isinstance(raw, dict)]
    return records[:limit]
