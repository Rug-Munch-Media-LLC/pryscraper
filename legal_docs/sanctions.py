"""OFAC SDN sanctions-list name screening — free downloads, cached.

Screens a name against the U.S. Treasury OFAC Specially Designated
Nationals (SDN) list. The list is published as free public downloads
(no key, no auth):

* JSON: ``https://www.treasury.gov/ofac/downloads/sdn.json`` (may 404 when
  OFAC retires a format — see fallback below).
* XML:  ``https://www.treasury.gov/ofac/downloads/sdn.xml`` — the rich
  format OFAC currently serves (``sdnEntry`` records with uid, first/last
  name, sdnType, programs, aka, addresses, citizenships, remarks).
* CSV:  ``https://www.treasury.gov/ofac/downloads/sdn.csv`` — legacy
  12-column flat file (number, name, country, remarks); last-resort
  fallback when both JSON and XML fail.

The parsed entry list is cached in-process (TTL 24h, configurable via
``PRY_LEGAL_OFAC_TTL_SECONDS``) and, when ``PRY_LEGAL_OFAC_CACHE_PATH`` is
set, on disk (``{"fetched_at": <epoch>, "entries": [...]}``) so repeated
calls never re-download the ~28MB XML.

Contract
--------
* :func:`screen_name` — async, never raises, returns ``list``. Matches every
  whitespace-separated token of ``name`` against the primary + aka names of
  each SDN entry (case/punctuation-insensitive, AND semantics).

Result shape
------------
``screen_name`` returns a list of:

    {
        "uid": "36",
        "name": "AEROCARIBBEAN AIRLINES",
        "sdn_type": "Entity",
        "programs": ["CUBA"],
        "title": None,
        "remarks": None,
        "citizenships": ["CU"],
        "akas": ["AERO-CARIBBEAN"],
        "matched_fields": ["primary"],
        "match_reason": "all 3 tokens matched (primary name)",
        "source": "ofac_sdn",
    }

Empty list on failure (all downloads unreachable, malformed payloads,
no match). Backoff: 2 retries, exponential (0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_SDN_JSON_URL = "https://www.treasury.gov/ofac/downloads/sdn.json"
_SDN_XML_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
_SDN_CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"

_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json,text/xml,text/csv,*/*;q=0.8",
}

_TTL_SECONDS_ENV = "PRY_LEGAL_OFAC_TTL_SECONDS"
_CACHE_PATH_ENV = "PRY_LEGAL_OFAC_CACHE_PATH"
_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_MAX_RESULTS = 50

# In-process cache of normalized SDN entries.
_ENTRIES_CACHE: list[dict[str, Any]] | None = None
_ENTRIES_CACHE_TS = 0.0

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _norm(text: str) -> str:
    """Normalize a name for matching: uppercase, alnum only, collapse spaces."""
    return _NON_ALNUM.sub(" ", text.upper()).strip()


def _ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get(_TTL_SECONDS_ENV, str(_DEFAULT_TTL_SECONDS))))
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECONDS


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _join_name(first: Any, last: Any) -> str | None:
    parts = [p for p in (_text(first), _text(last)) if p]
    return " ".join(parts) if parts else None


# ── Parsers (JSON / XML / legacy CSV -> normalized entries) ────────────
def _parse_json_entries(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    sdn_list = (
        payload.get("data", payload).get("sdnList")
        if isinstance(payload.get("data"), dict)
        else payload.get("sdnList")
    )
    if not isinstance(sdn_list, dict):
        return None
    entries = sdn_list.get("sdnEntry") or []
    if not isinstance(entries, list):
        return None
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parsed = _entry_from_fields(entry)
        if parsed is not None:
            out.append(parsed)
    return out or None


def _xml_local(tag: str) -> str:
    """Strip the XML namespace prefix from a tag (``{ns}uid`` -> ``uid``)."""
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _parse_xml_entries(raw: str) -> list[dict[str, Any]] | None:
    try:
        # ET.fromstring on the trusted treasury.gov SDN download. ElementTree
        # never resolves external entities; defusedxml is not a dependency.
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError:
        return None
    if _xml_local(root.tag) != "sdnList":
        return None
    out: list[dict[str, Any]] = []
    for entry in root:
        if _xml_local(entry.tag) != "sdnEntry":
            continue
        fields: dict[str, Any] = {}
        for child in entry:
            tag = _xml_local(child.tag)
            if tag in {
                "programList",
                "akaList",
                "addressList",
                "citizenshipList",
                "dateOfBirthList",
            }:
                if tag == "programList":
                    fields["programs"] = [_text(g.text) for g in child if _text(g.text)]
                elif tag == "akaList":
                    akas: list[str] = []
                    for aka in child:
                        if _xml_local(aka.tag) != "aka":
                            continue
                        name = _join_name(
                            next((c.text for c in aka if _xml_local(c.tag) == "firstName"), None),
                            next((c.text for c in aka if _xml_local(c.tag) == "lastName"), None),
                        )
                        if name:
                            akas.append(name)
                    fields["akas"] = akas
                elif tag == "citizenshipList":
                    fields["citizenships"] = [_text(g.text) for g in child if _text(g.text)]
                continue
            fields[tag] = child.text
        parsed = _entry_from_fields(fields)
        if parsed is not None:
            out.append(parsed)
    return out or None


def _parse_csv_entries(raw: str) -> list[dict[str, Any]] | None:
    """Parse the legacy headerless 12-column SDN.CSV (number,name,...,country,...,remarks)."""
    try:
        reader = csv.reader(io.StringIO(raw))
        rows = [row for row in reader if len(row) >= 2]
    except (csv.Error, UnicodeDecodeError):
        return None
    if not rows:
        return None
    out: list[dict[str, Any]] = []
    for row in rows:
        name = _text(row[1])
        if not name:
            continue
        country = _text(row[3]) if len(row) > 3 and row[3] != "-0-" else None
        remarks = _text(row[11]) if len(row) > 11 and row[11] != "-0-" else None
        out.append(
            {
                "uid": _text(row[0]),
                "first_name": name,
                "last_name": None,
                "sdn_type": None,
                "programs": [country] if country else [],
                "title": None,
                "remarks": remarks,
                "akas": [],
                "citizenships": [country] if country else [],
                "addresses": [],
                "source": "ofac_sdn",
            }
        )
    return out or None


def _entry_from_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a raw SDN entry dict (JSON or XML-derived) into the canonical record."""
    first = _text(fields.get("firstName"))
    last = _text(fields.get("lastName"))
    whole = _text(fields.get("wholeName") or fields.get("sdnName"))
    name = _join_name(first, last) or whole
    if not name:
        return None
    programs_raw = fields.get("programs")
    if programs_raw is None:
        programs_raw = fields.get("programList")
    if isinstance(programs_raw, dict):
        programs_raw = programs_raw.get("program")
    programs = [_text(p) for p in programs_raw] if isinstance(programs_raw, list) else []
    programs = [p for p in programs if p]
    return {
        "uid": _text(fields.get("uid")),
        "first_name": first,
        "last_name": last,
        "sdn_type": _text(fields.get("sdnType")),
        "programs": programs,
        "title": _text(fields.get("title")),
        "remarks": _text(fields.get("remarks")),
        "akas": [a for a in (fields.get("akas") or []) if isinstance(a, str) and a.strip()],
        "citizenships": [
            c for c in (fields.get("citizenships") or []) if isinstance(c, str) and c.strip()
        ],
        "addresses": [],
        "source": "ofac_sdn",
    }


# ── Fetching ───────────────────────────────────────────────────────────
async def _http_text(url: str) -> str | None:
    """GET ``url`` and return the raw text, or None on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_entries_network() -> list[dict[str, Any]] | None:
    """Try JSON -> XML -> CSV downloads; return normalized entries or None."""
    raw = await _http_text(_SDN_JSON_URL)
    if raw:
        try:
            parsed = _parse_json_entries(json.loads(raw))
        except json.JSONDecodeError:
            parsed = None
        if parsed:
            logger.info("legal_ofac_source_json")
            return parsed
    raw = await _http_text(_SDN_XML_URL)
    if raw:
        parsed = _parse_xml_entries(raw)
        if parsed:
            logger.info("legal_ofac_source_xml")
            return parsed
    raw = await _http_text(_SDN_CSV_URL)
    if raw:
        parsed = _parse_csv_entries(raw)
        if parsed:
            logger.info("legal_ofac_source_csv")
            return parsed
    return None


def _cache_path() -> str | None:
    path = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return path or None


def _read_cache_file(path: str) -> dict[str, Any] | None:
    """Sync disk-cache read (kept out of async bodies for ASYNC230)."""
    try:
        with open(path, encoding="utf-8") as fh:
            disk = json.load(fh)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return disk if isinstance(disk, dict) else None


def _write_cache_file(path: str, entries: list[dict[str, Any]]) -> None:
    """Sync disk-cache write (kept out of async bodies for ASYNC230)."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "entries": entries}, fh)
    except OSError:
        logger.warning("legal_ofac_cache_disk_write_failed")


async def _load_entries() -> list[dict[str, Any]] | None:
    """Return cached entries (in-process, then disk), else fetch + cache."""
    global _ENTRIES_CACHE, _ENTRIES_CACHE_TS
    now = time.monotonic()
    if _ENTRIES_CACHE is not None and (now - _ENTRIES_CACHE_TS) < _ttl_seconds():
        return _ENTRIES_CACHE

    path = _cache_path()
    if path:
        disk = _read_cache_file(path)
        if disk is not None and isinstance(disk.get("entries"), list):
            fetched_at = float(disk.get("fetched_at") or 0)
            if time.time() - fetched_at < _ttl_seconds():
                _ENTRIES_CACHE = disk["entries"]
                _ENTRIES_CACHE_TS = now
                logger.info("legal_ofac_cache_disk_hit")
                return _ENTRIES_CACHE
        logger.warning("legal_ofac_cache_disk_unreadable")

    entries = await _fetch_entries_network()
    if not entries:
        return _ENTRIES_CACHE  # stale in-process cache beats nothing
    _ENTRIES_CACHE = entries
    _ENTRIES_CACHE_TS = now
    if path:
        _write_cache_file(path, entries)
    return entries


# ── Screening ──────────────────────────────────────────────────────────
def _entry_name_pool(entry: dict[str, Any]) -> dict[str, str]:
    """Map ``primary`` / ``akaN`` labels to normalized name strings."""
    pool: dict[str, str] = {}
    primary = _join_name(entry.get("first_name"), entry.get("last_name"))
    if primary:
        pool["primary"] = _norm(primary)
    for i, aka in enumerate(entry.get("akas") or []):
        pool[f"aka{i}"] = _norm(aka)
    return pool


def _tokens(name: str) -> list[str]:
    return [tok for tok in _norm(name).split() if tok]


async def screen_name(name: str) -> list[dict[str, Any]]:
    """Screen a name against the OFAC SDN list.

    Args:
        name: Full name or business name to screen (e.g. ``"John Smith"``).

    Returns:
        List of matching SDN entries (see module docstring), capped at
        :data:`_MAX_RESULTS`. ``[]`` when nothing matches or the list cannot
        be loaded. Never raises.
    """
    try:
        return await _screen_name(name)
    except Exception:
        logger.exception("legal_ofac_screen_crashed", extra={"name": name})
        return []


async def _screen_name(name: str) -> list[dict[str, Any]]:
    tokens = _tokens(name)
    if not tokens:
        return []
    entries = await _load_entries()
    if not entries:
        return []
    matches: list[dict[str, Any]] = []
    for entry in entries:
        pool = _entry_name_pool(entry)
        if not pool:
            continue
        matched_fields: list[str] = []
        for label, norm_name in pool.items():
            if all(tok in norm_name for tok in tokens):
                matched_fields.append(label)
        if not matched_fields:
            continue
        matched_names = {label: pool[label] for label in matched_fields}
        reason = "all {n} token(s) matched ({fields})".format(
            n=len(tokens), fields=", ".join(sorted(matched_fields))
        )
        matches.append(
            {
                "uid": entry.get("uid"),
                "name": _join_name(entry.get("first_name"), entry.get("last_name"))
                or (entry.get("akas") or [None])[0],
                "sdn_type": entry.get("sdn_type"),
                "programs": entry.get("programs") or [],
                "title": entry.get("title"),
                "remarks": entry.get("remarks"),
                "citizenships": entry.get("citizenships") or [],
                "akas": entry.get("akas") or [],
                "matched_fields": matched_fields,
                "matched_names": matched_names,
                "match_reason": reason,
                "source": "ofac_sdn",
            }
        )
        if len(matches) >= _MAX_RESULTS:
            break
    matches.sort(key=lambda m: len(m.get("matched_names") or {}), reverse=True)
    return matches
