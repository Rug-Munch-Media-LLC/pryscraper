"""Marketplace parsing helpers — text cleanup, coercion, price parsing, HTML.

Internal helpers (``_``-prefixed) shared by the marketplace submodules;
not part of the public API.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import json
import re
from typing import Any

from lxml import html as lxml_html

# ── Shared small helpers ───────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\s+")


def _text(value: Any) -> str:
    """Collapse whitespace + unescape HTML entities on scraped text; "" for None."""
    return html.unescape(_WHITESPACE_RE.sub(" ", str(value or "")).strip())


def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce any numeric input to float; ``default`` on failure."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """Coerce any numeric input to int; ``default`` on failure."""
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


# Currency symbol → ISO-4217 code (best-effort; $ defaults to USD).
_SYMBOL_CURRENCY: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "CNY",
    "C$": "CAD",
    "CA$": "CAD",
    "A$": "AUD",
    "AU$": "AUD",
}
_PRICE_RE = re.compile(
    r"(?P<sym>\$\s?|€\s?|£\s?|¥\s?|C\$\s?|A\$\s?|CA\$\s?|AU\$\s?)?(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
)


def _price_parts(text: Any) -> tuple[float, str]:
    """Parse a price string into ``(amount, currency_code)``; (0.0, "") on failure.

    Handles "$1,234.56", "€ 99,90", "45.99", "12.345" (plain number).
    """
    match = _PRICE_RE.search(_text(text))
    if not match:
        return 0.0, ""
    raw = match.group("num")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")  # 1,234.56
    try:
        amount = float(raw)
    except ValueError:
        return 0.0, ""
    symbol = (match.group("sym") or "").strip()
    return amount, _SYMBOL_CURRENCY.get(symbol, "")


def _first_text(values: Any) -> str:
    """First non-empty text from an lxml text() result list."""
    if not isinstance(values, (list, tuple)):
        return _text(values)
    for value in values:
        cleaned = _text(value)
        if cleaned:
            return cleaned
    return ""


def _lxml_doc(html_text: str) -> Any:
    """Parse HTML into an lxml document; None on any parse failure."""
    if not html_text:
        return None
    try:
        return lxml_html.fromstring(html_text)
    except (ValueError, TypeError):
        return None


def _find_script_json(html_text: str, script_id: str) -> Any:
    """Parse a ``<script id="...">`` block's JSON payload; None on failure."""
    if not html_text:
        return None
    match = re.search(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except ValueError:
        return None


# Walmart redux state: `window.__WML_REDUX_INITIAL_STATE__ = {...};`
_REDUX_RE = re.compile(
    r"window\.__WML_REDUX_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.DOTALL,
)


def _find_redux_state(html_text: str) -> Any:
    """Parse Walmart's ``__WML_REDUX_INITIAL_STATE__`` JSON; None on failure."""
    if not html_text:
        return None
    match = _REDUX_RE.search(html_text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def _is_amazon_block(html_text: str, status: int) -> bool:
    """True when an Amazon response looks like an anti-bot / captcha page."""
    if status in (403, 503):
        return True
    lowered = (html_text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "robot check",
            "automated access",
            "enter the characters you see below",
            "api-services-support@amazon.com",
        )
    )
