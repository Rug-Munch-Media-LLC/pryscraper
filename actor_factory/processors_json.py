"""Pry - Apify Actor Factory: structured-data / JSON processors.

Schema.org JSON-LD extraction (entities + product prices) and the JSON
API processor that turns public-API responses into dataset items.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import re
from typing import Any

from actor_factory.processors_common import _base_item, _raw_html

# Matches quoted AND unquoted attribute forms - Yoast SEO (#1 WordPress
# plugin) emits <script type=application/ld+json class=...> unquoted,
# which is valid HTML5. Found via live back-testing.
_JSONLD_RE = re.compile(
    r"""<script[^>]+type=["']?application/ld\+json["']?[^>]*>(.*?)</script>""",
    re.I | re.S,
)


def _jsonld_objects(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        candidates = data.get("@graph", [data]) if isinstance(data, dict) else data
        for obj in candidates if isinstance(candidates, list) else [candidates]:
            if isinstance(obj, dict) and obj.get("@type"):
                out.append(obj)
    return out


def process_extract(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Pull schema.org JSON-LD entities (Recipe, Product, Review, Event,
    Course, JobPosting...) into clean per-item fields. Falls back to a
    metadata-only item when the page embeds no structured data."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    html = _raw_html(result) or ""
    wanted = options.get("types")  # e.g. ["Recipe"] - None means any
    entities: list[dict[str, Any]] = []
    for obj in _jsonld_objects(html):
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if wanted and not any(t in wanted for t in types):
            continue
        flat = {
            k: v
            for k, v in obj.items()
            if isinstance(v, (str, int, float, bool)) and k != "@context"
        }
        entities.append({"type": ",".join(str(t) for t in types), "fields": flat})
    if not entities:
        item["status"] = "skipped"
        item["error"] = "no matching structured data on page"
        item.pop("content", None)
        return item
    item.pop("content", None)
    item["extracted"] = {"entities": entities[:10]}
    return item


def _price_from_jsonld(html: str) -> tuple[float | None, str, str]:
    """Extract (price, currency, name) from schema.org/Product JSON-LD."""
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for node in candidates:
            graph = node.get("@graph") if isinstance(node, dict) else None
            for obj in ([node] if isinstance(node, dict) else []) + (graph or []):
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("@type", "")).lower() != "product":
                    continue
                offers = obj.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") or offers.get("lowPrice")
                currency = offers.get("priceCurrency", "")
                name = str(obj.get("name", ""))[:200]
                try:
                    return float(str(price).replace(",", "")), currency, name
                except (TypeError, ValueError):
                    continue
    return None, "", ""


def process_price(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Schema.org/Product structured-data-first price extraction."""
    item = _base_item(url, result)
    html = _raw_html(result)
    if item["status"] != "ok":
        return item
    price, currency, name = _price_from_jsonld(html)
    if price is None:
        item["status"] = "error"
        item["error"] = "no structured product price found"
        return item
    item["product"] = {
        "name": name,
        "price": price,
        "currency": currency or options.get("currency_hint", "USD"),
    }
    return item


# ── JSON API processor (public-API-backed Actors) ────────────────────────────


def _flatten_json(obj: Any, prefix: str = "", depth: int = 0, out: dict | None = None) -> dict:
    """Flatten nested dicts/lists into dot-notation keys (bounded)."""
    out = {} if out is None else out
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                _flatten_json(v, key, depth + 1, out)
            elif isinstance(v, (str, int, float, bool)) or v is None:
                out[key] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            _flatten_json(v, f"{prefix}[{i}]", depth + 1, out)
    return out


def process_jsondata(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Parse JSON API responses into structured dataset items.

    Powers the public-API-backed Actor lineup (GitHub, npm, PyPI, RDAP,
    iTunes, HN, exchange rates...): the engine fetches the URL, this
    processor turns the JSON body into clean items. Options:
      data_path - dot/bracket path to the array of interest (e.g. "items")
      max_items - cap per response (default 50)
    """
    item = _base_item(url, result)
    raw = result.get("raw_html") or item["content"] or ""
    text = raw.strip()
    # strip accidental markdown/code fences around the payload
    if text.startswith("```"):
        text = text.strip("`").lstrip("json\n").strip()
    start_obj = text.find("{")
    start_arr = text.find("[")
    # whichever container opens first wins - finding "{" first would
    # truncate a top-level array to its first element
    if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
        start = start_arr
    else:
        start = start_obj
    if start == -1:
        item["status"] = "skipped"
        item["error"] = "response is not JSON"
        item.pop("content", None)
        return item
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        item["status"] = "skipped"
        item["error"] = f"invalid JSON: {exc}"
        item.pop("content", None)
        return item

    data_path = options.get("data_path")
    if data_path:
        cur: Any = payload
        for part in re.findall(r"[^\[\]]+|\[\d+\]", str(data_path)):
            try:
                cur = cur[int(part[1:-1])] if part.startswith("[") else cur[part]
            except (KeyError, IndexError, TypeError, ValueError):
                cur = None
                break
        payload = cur if cur is not None else []

    records = payload if isinstance(payload, list) else [payload]
    max_items = int(options.get("max_items", 50) or 50)
    item.pop("content", None)
    item["data"] = {
        "records": [_flatten_json(r) for r in records[:max_items]],
        "count": min(len(records), max_items),
        "total_in_response": len(records),
    }
    return item
