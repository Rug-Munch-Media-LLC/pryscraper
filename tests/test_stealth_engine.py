# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the stealth engine: script generation, injection order, noise bounds.

All tests are pure string-level assertions — no browser, no Playwright, no
network. They verify the anti-fingerprint scripts contain the expected JS
patches and that ``generate_all()`` concatenates components in the documented
injection order.
"""

import json
import re
from pathlib import Path

import pytest

from stealth_engine import StealthEngine


def _noise_value(script: str) -> float:
    """Extract the numeric noise constant injected into a script."""
    m = re.search(r"const noise = ([0-9.eE+-]+);", script)
    assert m is not None, f"noise constant not found in script: {script[:200]}"
    return float(m.group(1))


# ── Injection order ─────────────────────────────────────────────


def test_generate_all_concatenates_all_five_components() -> None:
    s = StealthEngine()
    full = s.generate_all()
    assert "WebGLRenderingContext" in full
    assert "HTMLCanvasElement" in full
    assert "AudioBuffer" in full
    assert "measureText" in full
    assert "navigator, 'webdriver'" in full


def test_generate_all_injection_order() -> None:
    """Components must be injected in the documented order: webgl → canvas →
    audio → font → webdriver. Order matters because the last patched prototype
    wins on conflicting overrides and the webdriver hide must run last to
    remove automation indicators after other patches may re-expose them."""
    s = StealthEngine()
    full = s.generate_all()
    positions = [
        full.index("WebGLRenderingContext.prototype.getParameter"),
        full.index("HTMLCanvasElement.prototype.toDataURL"),
        full.index("AudioBuffer.prototype.getChannelData"),
        full.index("CanvasRenderingContext2D.prototype.measureText"),
        full.index("Object.defineProperty(navigator, 'webdriver'"),
    ]
    assert positions == sorted(positions), f"wrong injection order: {positions}"


def test_generate_all_scripts_are_self_contained_iife() -> None:
    """Each component should be an immediately-invoked function expression."""
    s = StealthEngine()
    for script in (
        s.webgl_noise(),
        s.canvas_noise(),
        s.audio_noise(),
        s.font_spoof(),
        s.webdriver_hide(),
    ):
        assert "(() => {" in script
        assert "})();" in script


# ── WebGL noise ─────────────────────────────────────────────────


def test_webgl_noise_bounds() -> None:
    noise = _noise_value(StealthEngine().webgl_noise())
    assert 0.0001 <= noise <= 0.001


def test_webgl_noise_spoofs_renderer_strings() -> None:
    script = StealthEngine().webgl_noise()
    assert "37445" in script  # UNMASKED_VENDOR_WEBGL
    assert "37446" in script  # UNMASKED_RENDERER_WEBGL
    assert "'Intel Inc.'" in script
    assert "'Intel Iris OpenGL Engine'" in script


def test_webgl_noise_hides_debug_extension() -> None:
    script = StealthEngine().webgl_noise()
    assert "WEBGL_debug_renderer_info" in script
    assert "return null" in script


# ── Canvas noise ────────────────────────────────────────────────


def test_canvas_noise_bounds() -> None:
    noise = _noise_value(StealthEngine().canvas_noise())
    assert 0.00005 <= noise <= 0.0005


def test_canvas_noise_patches_to_data_url() -> None:
    script = StealthEngine().canvas_noise()
    assert "HTMLCanvasElement.prototype.toDataURL" in script
    assert "getImageData" in script
    assert "putImageData" in script


# ── Audio noise ─────────────────────────────────────────────────


def test_audio_noise_patches_audio_buffer() -> None:
    script = StealthEngine().audio_noise()
    assert "AudioBuffer.prototype.getChannelData" in script
    assert "Math.random() - 0.5" in script


# ── Font spoof ──────────────────────────────────────────────────


def test_font_spoof_embeds_font_list() -> None:
    script = StealthEngine().font_spoof()
    match = re.search(r"const fonts = (\[.*?\]);", script, re.S)
    assert match is not None
    fonts = json.loads(match.group(1))
    assert "Arial" in fonts
    assert "Times New Roman" in fonts
    assert len(fonts) >= 6


def test_font_spoof_patches_measure_text() -> None:
    script = StealthEngine().font_spoof()
    assert "CanvasRenderingContext2D.prototype.measureText" in script
    assert "Math.random() - 0.5" in script


# ── Webdriver hide ──────────────────────────────────────────────


def test_webdriver_hide_removes_automation_indicators() -> None:
    script = StealthEngine().webdriver_hide()
    assert "navigator, 'webdriver'" in script
    assert "get: () => undefined" in script
    assert "navigator, 'plugins'" in script
    assert "navigator, 'languages'" in script
    assert "window.chrome = { runtime: {} }" in script


def test_webdriver_hide_mocks_permissions_query() -> None:
    script = StealthEngine().webdriver_hide()
    assert "navigator.permissions.query" in script
    assert "'notifications'" in script
    assert "'denied'" in script


# ── Human behavior scripts ──────────────────────────────────────


def test_human_mouse_script_bezier_logic() -> None:
    script = StealthEngine().human_mouse_script()
    assert "__pry_mouse" in script
    assert "Math.pow(1 - t, 3)" in script  # cubic ease-out bezier
    assert "__pry_humanClick" in script
    assert "dispatchEvent(new MouseEvent('click'" in script


def test_human_type_script_variable_delays() -> None:
    script = StealthEngine().human_type_script()
    assert "__pry_humanType" in script
    assert "Math.random() * 80 + 40" in script  # char delay
    assert "Math.random() * 200 + 100" in script  # space delay
    assert "dispatchEvent(new Event('change'" in script


# ── save_scripts ────────────────────────────────────────────────


def test_save_scripts_writes_all_six_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import stealth_engine

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
    written = {p.name for p in tmp_path.iterdir()}
    assert expected == written
    for name in expected:
        content = (tmp_path / name).read_text()
        assert content.strip(), f"{name} written but empty"
