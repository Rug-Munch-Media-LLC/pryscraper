"""Tag network/sleep-touching tests at collection so PR gates can exclude them.

Registered via `-p pytest_netmarks` in pyproject addopts. Marks only; no test
is skipped here, so a plain `pytest` run behaves exactly as before.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_NET = re.compile(r"^\s*(?:import|from)\s+(requests|httpx|aiohttp|urllib|socket|websockets|websocket)\b", re.M)
_SLEEP = re.compile(r"\b(?:time|asyncio)\.sleep\(")
_CACHE: dict[str, bool] = {}


def _is_network(path: pathlib.Path) -> bool:
    key = str(path)
    if key not in _CACHE:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            _CACHE[key] = False
        else:
            _CACHE[key] = bool(_NET.search(src) or _SLEEP.search(src))
    return _CACHE[key]


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = getattr(item, "path", None) or pathlib.Path(str(item.fspath))
        if pathlib.Path(path).suffix != ".py":
            continue
        if _is_network(pathlib.Path(path)) and item.get_closest_marker("network") is None:
            item.add_marker(pytest.mark.network)
