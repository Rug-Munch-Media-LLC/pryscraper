"""File iterators for the JSON store importer.

Split from import_json.py on 2026-08-29 to clear the 200-line structure cap.
Pure iteration helpers, re-exported from import_json so existing imports are
unchanged.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any


def _iter_json_files(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object from a JSON store file or directory.

    A missing store yields nothing. An unreadable or malformed store raises:
    a swallowed error here becomes a ``counts`` entry of 0 for that store,
    which reads as "imported, nothing to do" rather than "data lost".
    """
    if not path.exists():
        return
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"unreadable JSON store {path}") from e
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict):
                    yield d
        elif isinstance(data, dict):
            yield data
        return
    for f in path.glob("*.json"):
        yield from _iter_json_files(f)


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSON object from a JSONL store.

    A missing store yields nothing. An unreadable store or a malformed line
    raises: silently skipping either would report the store as imported with
    a row count that understates the data actually lost.
    """
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"malformed JSONL at {path}:{lineno}") from e
