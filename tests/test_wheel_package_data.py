"""The built wheel must ship the FastAPI UI templates, not just .py modules.

`pry.api.routers.core.app_ui` reads ``api/templates/app/ui.css`` with
``Path.read_text`` at import time. setuptools only ships Python modules, so
without package-data the wheel installs cleanly and then dies:

    FileNotFoundError: .../pry/api/templates/app/ui.css

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PREFIX = "pry/api/templates/"


def _pyproject() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_package_data_declares_api_templates() -> None:
    """Guard the config itself: the glob must exist in [package-data]."""
    text = _pyproject()
    assert "api/templates/" in text, "package-data lost the api/templates glob"
    assert "api/templates/**/*" in text


@lru_cache(maxsize=1)
def _build_wheel() -> Path:
    """Build one wheel for the whole test session and return its path."""
    if not importlib.util.find_spec("build"):
        pytest.skip("`build` is not installed; cannot inspect a wheel")
    out = Path(tempfile.mkdtemp(prefix="pry-wheel-"))
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout}\n{proc.stderr}"
    wheels = sorted(out.glob("pryscraper_mcp-*.whl"))
    assert wheels, f"no wheel produced in {out}"
    return wheels[-1]


def test_wheel_contains_api_templates() -> None:
    wheel = _build_wheel()
    with zipfile.ZipFile(wheel) as zf:
        members = zf.namelist()
    templates = [m for m in members if m.startswith(TEMPLATE_PREFIX)]
    assert templates, f"wheel {wheel.name} has no {TEMPLATE_PREFIX} files"
    assert any(m.endswith("app/ui.css") for m in templates), templates
