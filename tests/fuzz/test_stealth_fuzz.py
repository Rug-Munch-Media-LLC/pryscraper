# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
"""Fuzz tests for StealthEngine — invariants across many random draws.

StealthEngine is driven by ``random.SystemRandom``, so the "input" is the
entropy itself. These tests treat the RNG as the fuzz target: over hundreds
of draws the generated scripts must stay structurally valid, the injected
noise constants must stay inside their documented bounds, and the complete
script must keep the documented component order. Any formatting/JS break on
a particular draw would only show up across many draws — exactly what a
property test is for.
"""

import json
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import pry.engine.stealth_engine as stealth_engine
from pry.engine.stealth_engine import StealthEngine

_NOISE_RE = re.compile(r"const noise = ([0-9.eE+-]+);")


def _noise_value(script: str) -> float:
    match = _NOISE_RE.search(script)
    assert match is not None, f"noise constant missing from script: {script[:200]!r}"
    return float(match.group(1))


def _assert_valid_script(script: str) -> None:
    """Every generated component must be a non-empty, self-contained IIFE."""
    assert isinstance(script, str)
    assert script.strip(), "script must not be empty"
    assert "(() => {" in script, "script must be an IIFE"
    assert "})();" in script, "script must close its IIFE"


@settings(max_examples=100, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_webgl_noise_stays_in_bounds(_seed: int) -> None:
    """WebGL noise must remain in the documented [0.0001, 0.001] band."""
    engine = StealthEngine()
    for _ in range(20):
        script = engine.webgl_noise()
        _assert_valid_script(script)
        assert 0.0001 <= _noise_value(script) <= 0.001


@settings(max_examples=100, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_canvas_noise_stays_in_bounds(_seed: int) -> None:
    """Canvas noise must remain in the documented [0.00005, 0.0005] band."""
    engine = StealthEngine()
    for _ in range(20):
        script = engine.canvas_noise()
        _assert_valid_script(script)
        assert 0.00005 <= _noise_value(script) <= 0.0005


@settings(max_examples=100, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_all_generators_produce_valid_scripts(_seed: int) -> None:
    """Every generator must produce a structurally valid script every time."""
    engine = StealthEngine()
    for _ in range(20):
        for script in (
            engine.webgl_noise(),
            engine.canvas_noise(),
            engine.audio_noise(),
            engine.font_spoof(),
            engine.webdriver_hide(),
            engine.human_mouse_script(),
            engine.human_type_script(),
        ):
            _assert_valid_script(script)


@settings(max_examples=50, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_generate_all_keeps_component_order(_seed: int) -> None:
    """The concatenated script must keep webgl → canvas → audio → font → wd order.

    Order matters: the last patched prototype wins on conflicting overrides
    and webdriver hide must run last (see test_stealth_engine.py).
    """
    engine = StealthEngine()
    for _ in range(10):
        full = engine.generate_all()
        positions = [
            full.index("WebGLRenderingContext.prototype.getParameter"),
            full.index("HTMLCanvasElement.prototype.toDataURL"),
            full.index("AudioBuffer.prototype.getChannelData"),
            full.index("CanvasRenderingContext2D.prototype.measureText"),
            full.index("Object.defineProperty(navigator, 'webdriver'"),
        ]
        assert positions == sorted(positions), f"component order violated: {positions}"


@settings(max_examples=50, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_font_spoof_always_embeds_valid_font_list(_seed: int) -> None:
    """font_spoof must always embed a parseable JSON font list with Arial."""
    engine = StealthEngine()
    for _ in range(10):
        script = engine.font_spoof()
        match = re.search(r"const fonts = (\[.*?\]);", script, re.S)
        assert match is not None, f"font list missing: {script[:200]!r}"
        fonts = json.loads(match.group(1))
        assert "Arial" in fonts
        assert len(fonts) >= 6


@settings(max_examples=50, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(_seed=st.integers())
def test_generated_scripts_are_unique_draws(_seed: int) -> None:
    """Randomized components must differ across draws (real entropy, not const).

    SystemRandom.uniform produces ~53 bits of entropy per draw; two formatted
    noise values colliding across 20 draws is effectively impossible. If the
    engine ever hardcodes a constant, this fails.
    """
    engine = StealthEngine()
    webgl_draws = {engine.webgl_noise() for _ in range(20)}
    canvas_draws = {engine.canvas_noise() for _ in range(20)}
    assert len(webgl_draws) > 1, "webgl_noise returned identical scripts 20x"
    assert len(canvas_draws) > 1, "canvas_noise returned identical scripts 20x"


@settings(
    max_examples=10,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(_seed=st.integers())
def test_save_scripts_writes_all_files(
    _seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save_scripts must write all six files, all non-empty, every draw."""

    monkeypatch.setattr(stealth_engine, "SCRIPTS_DIR", tmp_path)
    StealthEngine().save_scripts()
    expected = {
        "webgl_noise.js",
        "canvas_noise.js",
        "audio_noise.js",
        "webdriver_hide.js",
        "human_mouse.js",
        "human_type.js",
    }
    assert expected == {p.name for p in tmp_path.iterdir()}
    for name in expected:
        assert (tmp_path / name).read_text().strip(), f"{name} written but empty"
