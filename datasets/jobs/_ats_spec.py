"""Declarative field interpreter for the ATS board specs in ``ats.json``.

Each board spec describes *how* to fold a raw board payload into the
common listing/detail schemas; the functions here are the generic
verbs that interpret those specs (dot-path lookup, first-truthy key,
location rebuilds, remote detection, compensation/requirements
extraction, URL fallbacks). No I/O happens here — see ``ats.py`` for
the HTTP layer and public entry points.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

_REMOTE_STRINGS = {"remote", "yes", "true", "fully remote", "fully_remote"}


def norm_dt(value: Any) -> str:
    """Best-effort normalization of a posting date to ISO-8601 UTC."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and value > 0:
        try:
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    except ValueError:
        return str(value)


def strip_html(text: str) -> str:
    """Strip HTML tags into readable plain text."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|div|li|ul|ol|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", html.unescape(text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def dig(obj: Any, path: str) -> Any:
    """Follow a dot-path through nested dicts; None when the path breaks."""
    for part in path.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def first(raw: dict[str, Any], spec: Any) -> Any:
    """First truthy value among the spec's key(s)."""
    for key in spec if isinstance(spec, list) else [spec]:
        if raw.get(key):
            return raw[key]
    return None


def join(raw: dict[str, Any], keys: list[str]) -> str:
    """Comma-join the non-empty string values of the given flat keys."""
    return ", ".join(str(raw.get(k) or "").strip() for k in keys if str(raw.get(k) or "").strip())


def loc_structured(raw: dict[str, Any]) -> str:
    """Workable: rebuild a location label from structured location fields."""
    locs = raw.get("locations")
    if isinstance(locs, list) and locs:
        parts: list[str] = []
        for loc in locs:
            if isinstance(loc, dict):
                bits = [str(loc.get(k) or "").strip() for k in ("city", "region", "country")]
            else:
                bits = [str(loc).strip()]
            bits = [b for b in bits if b]
            if bits:
                parts.append(", ".join(bits))
        if parts:
            return "; ".join(parts)
    single = raw.get("location")
    if isinstance(single, dict):
        bits = [str(single.get(k) or "").strip() for k in ("city", "region", "country")]
        bits = [b for b in bits if b]
        if bits:
            return ", ".join(bits)
    return join(raw, ["city", "state", "country"]) or str(single or "").strip()


def loc(raw: dict[str, Any], spec: dict[str, Any]) -> str:
    """Location label per spec: path / any / join_keys / structured / sr."""
    if spec.get("structured"):
        return loc_structured(raw)
    if spec.get("sr"):
        value = raw.get("location")
        return (
            join(value, ["city", "region", "country"])
            if isinstance(value, dict)
            else str(value or "")
        )
    if "path" in spec:
        return str(dig(raw, spec["path"]) or "")
    for key in spec.get("any", ()):
        value = dig(raw, key)
        if isinstance(value, list) and value:
            return ", ".join(str(x) for x in value)
        if isinstance(value, str) and value.strip():
            return value
    return join(raw, spec.get("join_keys", []))


def remote_meta(metadata: Any) -> bool:
    """Greenhouse: remote flag hidden in board metadata entries."""
    for meta in metadata or []:
        if not isinstance(meta, dict) or "remote" not in str(meta.get("name") or "").lower():
            continue
        value = meta.get("value")
        if value is True or (isinstance(value, str) and value.strip().lower() in _REMOTE_STRINGS):
            return True
    return False


def remote(raw: dict[str, Any], spec: dict[str, Any], location: str) -> bool:
    """Remote detection per spec: truthy flags, remote-ish strings, hints."""
    if any(raw.get(k) for k in spec.get("keys", ())):
        return True
    for key in spec.get("str_keys", ()):
        value = raw.get(key)
        if value is True or (isinstance(value, str) and value.strip().lower() in _REMOTE_STRINGS):
            return True
    if spec.get("nested") and dig(raw, spec["nested"]):
        return True
    if spec.get("metadata_remote") and remote_meta(raw.get("metadata")):
        return True
    return bool(spec.get("location_hint") and "remote" in location.lower())


def comp(raw: dict[str, Any], spec: dict[str, Any] | None) -> str:
    """Compensation string per spec kind (metadata/range/keys/field)."""
    if not spec:
        return ""
    kind = spec.get("type")
    if kind == "metadata_scan":
        out: list[str] = []
        for meta in raw.get("metadata") or []:
            if not isinstance(meta, dict):
                continue
            name = str(meta.get("name") or "")
            if not re.search(r"comp|salary|pay|range", name, re.I):
                continue
            value = meta.get("value")
            if value is None:
                continue
            if isinstance(value, dict) and value.get("amount") is not None:
                out.append(f"{name}: {value['amount']} {value.get('unit') or ''}".strip())
            elif not isinstance(value, dict):
                out.append(f"{name}: {value}")
        return "; ".join(out)
    if kind == "keys":
        source = dig(raw, spec.get("path") or "")
        if isinstance(source, dict):
            for key in spec["keys"]:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""
    if kind in ("range", "recruitee_range"):
        source = dig(raw, spec["path"]) if spec.get("path") else raw
        if not isinstance(source, dict):
            return ""
        low, high = source.get(spec["min"]), source.get(spec["max"])
        if low is None and high is None:
            return ""
        band = f"{low or ''} - {high or ''}".strip(" -")
        currency = str(source.get(spec["currency"]) or "")
        period = str(source.get(spec["period"]) or "")
        parts = [currency, band, period] if kind == "recruitee_range" else [band, currency, period]
        return " ".join(p for p in parts if p).strip()
    if kind == "field":
        return next((str(raw[k]) for k in spec["any"] if raw.get(k)), "")
    return ""


def req_lists(lists: Any) -> str:
    """Lever: extract requirement/qualification sections from ``lists``."""
    if not isinstance(lists, list):
        return ""
    chunks: list[str] = []
    for section in lists:
        if not isinstance(section, dict):
            continue
        text = str(section.get("text") or "").lower()
        if not re.search(r"requirement|qualif|what.*(need|bring|expect)", text):
            continue
        content = section.get("content")
        if isinstance(content, list):
            chunks += [c for c in (strip_html(str(i)) if i else "" for i in content) if c]
    return "\n".join(chunks)


def req_additional(additional: Any) -> str:
    """Ashby: extract requirement blocks from ``additionalDescriptions``."""
    if not isinstance(additional, list):
        return ""
    chunks: list[str] = []
    for block in additional:
        if not isinstance(block, dict):
            continue
        typ = str(block.get("type") or "").lower()
        value = block.get("value")
        keep = typ in _REQ_TYPES or "requirement" in typ or "qualif" in typ
        if keep and isinstance(value, str) and value.strip():
            chunks.append(strip_html(value))
    return "\n".join(chunks)


_REQ_TYPES = {
    "requirements",
    "qualifications",
    "minimum_qualifications",
    "what_youll_need",
    "what_you_need",
    "you_have",
    "responsibilities",
}


def text(raw: dict[str, Any], spec: dict[str, Any] | None) -> str:
    """Extract description/requirements text per spec kind."""
    if not spec:
        return ""
    kind = spec.get("type")
    if kind == "lists_scan":
        return req_lists(raw.get("lists"))
    if kind == "additional_scan":
        return req_additional(raw.get("additionalDescriptions"))
    if kind == "field":
        return next((str(raw[k]) for k in spec["any"] if raw.get(k)), "")
    for key in spec.get("plain_any", ()):
        if raw.get(key):
            return str(raw[key])
    if spec.get("plain") and raw.get(spec["plain"]):
        return str(raw[spec["plain"]])
    for path in spec.get("html_any", ()):
        value = dig(raw, path)
        if value:
            return strip_html(str(value))
    return ""


def url(raw: dict[str, Any], spec: dict[str, Any], company: str, job_id: str = "") -> str:
    """Listing/detail URL: first truthy key, else field/job_id template."""
    for key in spec.get("any", ()):
        value = str(raw.get(key) or "")
        if value:
            return value
    template = spec.get("template")
    if not template:
        return ""
    value = str(raw.get(spec["field"]) or "") if spec.get("field") else job_id
    return template.format(company=company, v=value, job_id=job_id) if value else ""


def extract(data: Any, spec: dict[str, Any]) -> list[Any]:
    """Pull the raw job list out of a board payload."""
    if isinstance(data, list):
        return data if spec.get("root_list") else []
    if isinstance(data, dict):
        for path in spec.get("container", ()):
            value = dig(data, path)
            if isinstance(value, list):
                return value
    return []


def norm(raw: dict[str, Any], spec: dict[str, Any], company: str) -> dict[str, Any]:
    """Fold one raw board item into the common listing schema."""
    fields = spec["fields"]
    location = loc(raw, fields["location"])
    return {
        "id": str(first(raw, fields["id"]) or ""),
        "title": str(first(raw, fields["title"]) or ""),
        "company": company,
        "location": location,
        "remote": remote(raw, fields["remote"], location),
        "url": url(raw, fields["url"], company),
        "posted_at": norm_dt(first(raw, fields["posted_at"])),
    }


def detail(
    item: dict[str, Any], spec: dict[str, Any], company: str, job_id: str = ""
) -> dict[str, Any]:
    """Fold one raw board item/response into the common detail schema."""
    return {
        "title": str(first(item, spec["title"]) or ""),
        "company": company,
        "location": loc(item, spec["location"]),
        "description": text(item, spec.get("description")),
        "requirements": text(item, spec.get("requirements")),
        "compensation": comp(item, spec.get("compensation")),
        "url": url(item, spec["url"], company, job_id),
    }
