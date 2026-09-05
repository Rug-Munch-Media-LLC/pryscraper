"""Google Maps embedded JS blob decoding for local_data.places.

Split from ``places.py``: extraction and decoding of the undocumented
``window._p`` / ``window.APP_INITIALIZATION_STATE`` JS blobs. These blobs
are undocumented; Google moves the indexes without notice, so this parser
is deliberately shape-based and defensive — every field defaults to
``""`` / ``None`` rather than raising.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from datasets.local_data.places_config import _ANTI_BOT_SIGNALS, _BLOB_ASSIGN_RE

if TYPE_CHECKING:
    from collections.abc import Iterator


def _extract_js_value(html: str, start: int) -> str | None:
    """Return the JS literal (string or array) beginning at ``start``.

    ``start`` is the position just after ``window.<name> =``. Scans either
    to the closing unescaped quote (string literal) or to the matching
    close bracket (array literal, respecting nested strings).
    """
    i = start
    n = len(html)
    while i < n and html[i] in " \t\r\n":
        i += 1
    if i >= n:
        return None
    first = html[i]
    if first == '"':
        j = i + 1
        while j < n:
            c = html[j]
            if c == "\\":
                j += 2
                continue
            if c == '"':
                return html[i : j + 1]
            j += 1
        return None
    if first == "[":
        depth = 0
        j = i
        in_str = False
        while j < n:
            c = html[j]
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        return html[i : j + 1]
            j += 1
        return None
    return None


def _js_unescape(raw: str) -> str:
    """Decode a JS string literal (\\xNN / \\uNNNN escapes) to text."""
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    out: list[str] = []
    i = 0
    n = len(raw)
    simple = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        '"': '"',
        "'": "'",
        "\\": "\\",
        "/": "/",
    }
    while i < n:
        c = raw[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "x" and i + 3 < n:
            try:
                out.append(chr(int(raw[i + 2 : i + 4], 16)))
            except ValueError:
                out.append("x")
            i += 4
            continue
        if nxt == "u" and i + 5 < n:
            try:
                out.append(chr(int(raw[i + 2 : i + 6], 16)))
            except ValueError:
                out.append("u")
            i += 6
            continue
        out.append(simple.get(nxt, nxt))
        i += 2
    return "".join(out)


def _js_escapes_to_json(text: str) -> str:
    """Convert JS escapes inside string literals of a JSON-ish array to JSON.

    Google's ``APP_INITIALIZATION_STATE`` arrays use JS ``\\xNN`` escapes
    that are not valid JSON; this rewrites string tokens to JSON escapes.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != '"':
            out.append(c)
            i += 1
            continue
        j = i + 1
        seg = ['"']
        while j < n:
            ch = text[j]
            if ch == "\\" and j + 1 < n:
                nxt = text[j + 1]
                if nxt == "x" and j + 3 < n:
                    seg.append("\\u00" + text[j + 2 : j + 4])
                    j += 4
                    continue
                if nxt == "u" and j + 5 < n:
                    seg.append("\\u" + text[j + 2 : j + 6])
                    j += 6
                    continue
                seg.append("\\" + nxt)
                j += 2
                continue
            if ch == '"':
                seg.append('"')
                j += 1
                break
            seg.append(ch)
            j += 1
        out.append("".join(seg))
        i = j
    return "".join(out)


def _decode_js_value(raw: str) -> Any:
    """Decode a JS literal (string or array) to a Python object."""
    if raw.startswith('"'):
        decoded = _js_unescape(raw)
        try:
            return json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            return decoded
    converted = _js_escapes_to_json(raw)
    try:
        return json.loads(converted)
    except (json.JSONDecodeError, ValueError):
        return None


def _jsonify(value: Any) -> Any:
    """Re-parse nested JSON strings (double-encoded ``_p`` blobs)."""
    seen = 0
    while isinstance(value, str) and seen < 3:
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            break
        seen += 1
    return value


def _extract_blobs(html: str) -> list[Any]:
    """Decode embedded Google Maps JSON blobs into Python objects.

    Supports ``window._p`` (a JS string literal that is itself JSON, often
    double-encoded and full of ``\\xNN`` escapes) and
    ``window.APP_INITIALIZATION_STATE`` (a raw JS array). Returns an empty
    list when nothing decodes — callers must treat that as "no data", not
    an error.
    """
    decoded: list[Any] = []
    for m in _BLOB_ASSIGN_RE.finditer(html):
        raw = _extract_js_value(html, m.end())
        if not raw:
            continue
        value = _decode_js_value(raw)
        if value is None:
            continue
        decoded.append(_jsonify(value))
    return decoded


def _iter_values(obj: Any, depth: int = 0) -> Iterator[Any]:
    """Yield every nested list/dict value up to ``depth``."""
    if depth > 8:
        return
    if isinstance(obj, list):
        yield obj
        for item in obj:
            yield from _iter_values(item, depth + 1)
    elif isinstance(obj, dict):
        yield obj
        for item in obj.values():
            yield from _iter_values(item, depth + 1)


def _is_anti_bot(html: str) -> bool:
    """Detect consent/captcha/"unusual traffic" walls in the first 300 KB."""
    low = html[:300_000].lower()
    return any(sig in low for sig in _ANTI_BOT_SIGNALS)
