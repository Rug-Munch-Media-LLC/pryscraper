"""Sportsbook registry — data-driven loader, statistics and validation.

The ~112-book registry lives as plain JSON (data, not code) under
``data/books.json`` and is loaded at import time into :data:`BOOKS`.
This module owns the registry vocabulary (:data:`CATEGORIES`,
:data:`METHODS`), the :func:`books_coverage` statistics endpoint and the
:func:`validate_registry` integrity check.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets.sports_data.books_normalize import _as_text

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Valid registry vocabularies ──────────────────────────────────────────
CATEGORIES: tuple[str, ...] = ("us", "offshore", "eu", "uk", "asian")
METHODS: tuple[str, ...] = ("json", "next_data", "nuxT", "init_state", "html", "browser")

# ── BOOKS registry: ~110 real sportsbooks ────────────────────────────────
# Methods: "json" (internal API), "next_data" (__NEXT_DATA__), "nuxT"
# (__NUXT__), "init_state" (__INITIAL_STATE__ / _dida_config_), "html"
# (server-rendered tables), "browser" (JS SPA — needs the browser tier).
# Confidence is a 0..1 estimate of how reliably we get clean odds today.
# geo_required=True books are geo-fenced (US state, Asia, etc.) and get
# Webshare residential proxy routing on the plain-HTTP attempt.
# The registry itself is data-driven (JSON) — see data/books.json.
_BOOK_DEFS: list[dict[str, Any]] = _load_json("books.json")

BOOKS: dict[str, dict[str, Any]] = {b["id"]: b for b in _BOOK_DEFS}


# ── Registry statistics ──────────────────────────────────────────────────
def books_coverage() -> dict[str, Any]:
    """Count books by category, geo requirement and extraction method.

    Returns:
        ``{total, by_category, by_method, geo_required: {true, false},
        categories, methods}``. Never raises.
    """
    by_category: dict[str, int] = {}
    by_method: dict[str, int] = {}
    geo_true = 0
    for book in BOOKS.values():
        by_category[book["category"]] = by_category.get(book["category"], 0) + 1
        by_method[book["method"]] = by_method.get(book["method"], 0) + 1
        if book["geo_required"]:
            geo_true += 1
    return {
        "total": len(BOOKS),
        "by_category": dict(sorted(by_category.items())),
        "by_method": dict(sorted(by_method.items())),
        "geo_required": {"true": geo_true, "false": len(BOOKS) - geo_true},
        "categories": sorted(CATEGORIES),
        "methods": sorted(METHODS),
    }


def validate_registry() -> list[str]:
    """Return a list of registry-integrity problems (empty when consistent)."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for book_id, book in BOOKS.items():
        if book.get("id") != book_id:
            problems.append(f"id mismatch: {book_id} != {book.get('id')}")
        if book_id in seen_ids:
            problems.append(f"duplicate id: {book_id}")
        seen_ids.add(book_id)
        name = _as_text(book.get("name"))
        if name is not None:
            if name in seen_names:
                problems.append(f"duplicate name: {name}")
            seen_names.add(name)
        if book.get("category") not in CATEGORIES:
            problems.append(f"invalid category: {book_id}")
        if book.get("method") not in METHODS:
            problems.append(f"invalid method: {book_id}")
        confidence = book.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            problems.append(f"invalid confidence: {book_id}")
        if not isinstance(book.get("geo_required"), bool):
            problems.append(f"geo_required not bool: {book_id}")
        template = book.get("odds_url_template")
        if not isinstance(template, str) or not template.startswith("https://"):
            problems.append(f"invalid odds_url_template: {book_id}")
        for field in ("name", "region", "notes"):
            if not isinstance(book.get(field), str):
                problems.append(f"{field} missing: {book_id}")
    return problems
