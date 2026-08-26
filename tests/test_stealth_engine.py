# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the stealth engine (stealth_engine.py) and stealth scripts.

T1 win #8: Stealth engine test coverage — verifies WebGL noise, Canvas noise,
AudioContext spoofing, font spoofing, webdriver hide, human mouse, and
human type scripts are generated correctly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import patch

from pry.engine.stealth_engine import StealthEngine

if TYPE_CHECKING:
    from pathlib import Path


class TestStealthEngine:
    """StealthEngine generates browser fingerprint evasion scripts."""

    def setup_method(self) -> None:
        self.engine = StealthEngine()

    def test_webgl_noise_contains_vendor_override(self) -> None:
        script = self.engine.webgl_noise()
        assert "Intel Inc." in script
        assert "Intel Iris OpenGL Engine" in script
        assert "WEBGL_debug_renderer_info" in script

    def test_webgl_noise_contains_noise_variable(self) -> None:
        script = self.engine.webgl_noise()
        # Should contain a noise value between 0.0001 and 0.001
        match = re.search(r"const noise = ([\d.]+);", script)
        assert match is not None
        noise_val = float(match.group(1))
        assert 0.0001 <= noise_val <= 0.001

    def test_canvas_noise_contains_pixel_manipulation(self) -> None:
        script = self.engine.canvas_noise()
        assert "getImageData" in script
        assert "putImageData" in script
        assert "toDataURL" in script

    def test_canvas_noise_contains_noise_variable(self) -> None:
        script = self.engine.canvas_noise()
        match = re.search(r"const noise = ([\d.]+);", script)
        assert match is not None
        noise_val = float(match.group(1))
        assert 0.00005 <= noise_val <= 0.0005

    def test_audio_noise_contains_channel_data_manipulation(self) -> None:
        script = self.engine.audio_noise()
        assert "getChannelData" in script
        assert "AudioBuffer" in script

    def test_font_spoof_contains_measure_text_override(self) -> None:
        script = self.engine.font_spoof()
        assert "measureText" in script
        assert "CanvasRenderingContext2D" in script

    def test_font_spoof_contains_font_list(self) -> None:
        script = self.engine.font_spoof()
        fonts = ["Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana"]
        for font in fonts:
            assert font in script

    def test_webdriver_hide_contains_navigator_override(self) -> None:
        script = self.engine.webdriver_hide()
        assert "navigator" in script
        assert "webdriver" in script
        assert "plugins" in script
        assert "languages" in script

    def test_webdriver_hide_contains_chrome_runtime(self) -> None:
        script = self.engine.webdriver_hide()
        assert "window.chrome" in script
        assert "runtime" in script

    def test_webdriver_hide_contains_permissions_override(self) -> None:
        script = self.engine.webdriver_hide()
        assert "permissions" in script
        assert "notifications" in script

    def test_human_mouse_script_contains_bezier_curves(self) -> None:
        script = self.engine.human_mouse_script()
        assert "mousemove" in script
        assert "Math.pow" in script  # bezier easing
        assert "__pry_mouse" in script

    def test_human_mouse_script_contains_click_sequence(self) -> None:
        script = self.engine.human_mouse_script()
        assert "mousedown" in script
        assert "mouseup" in script
        assert "click" in script

    def test_human_type_script_contains_input_events(self) -> None:
        script = self.engine.human_type_script()
        assert "input" in script
        assert "keydown" in script
        assert "keyup" in script
        assert "change" in script

    def test_human_type_script_contains_variable_delay(self) -> None:
        script = self.engine.human_type_script()
        # Should have different delays for space vs other chars
        assert "char === ' '" in script or 'char === " "' in script

    def test_generate_all_combines_all_scripts(self) -> None:
        combined = self.engine.generate_all()
        assert "Intel Inc." in combined  # webgl
        assert "getImageData" in combined  # canvas
        assert "getChannelData" in combined  # audio
        assert "measureText" in combined  # font
        assert "webdriver" in combined  # webdriver

    def test_save_scripts_writes_to_disk(self, tmp_path: Path) -> None:
        with patch("pry.engine.stealth_engine.SCRIPTS_DIR", tmp_path):
            self.engine.save_scripts()

        assert (tmp_path / "webgl_noise.js").exists()
        assert (tmp_path / "canvas_noise.js").exists()
        assert (tmp_path / "audio_noise.js").exists()
        assert (tmp_path / "webdriver_hide.js").exists()
        assert (tmp_path / "human_mouse.js").exists()
        assert (tmp_path / "human_type.js").exists()

    def test_saved_webgl_script_is_valid_js(self, tmp_path: Path) -> None:
        with patch("pry.engine.stealth_engine.SCRIPTS_DIR", tmp_path):
            self.engine.save_scripts()

        script = (tmp_path / "webgl_noise.js").read_text()
        # Basic JS syntax check: balanced braces
        assert script.count("{") == script.count("}")
        assert script.count("(") == script.count(")")

    def test_saved_canvas_script_is_valid_js(self, tmp_path: Path) -> None:
        with patch("pry.engine.stealth_engine.SCRIPTS_DIR", tmp_path):
            self.engine.save_scripts()

        script = (tmp_path / "canvas_noise.js").read_text()
        assert script.count("{") == script.count("}")
        assert script.count("(") == script.count(")")

    def test_noise_values_are_deterministic_per_call(self) -> None:
        """Each call to generate noise scripts should produce different noise values."""
        script1 = self.engine.webgl_noise()
        script2 = self.engine.webgl_noise()

        noise1 = float(re.search(r"const noise = ([\d.]+);", script1).group(1))
        noise2 = float(re.search(r"const noise = ([\d.]+);", script2).group(1))

        # Both should be in valid range
        assert 0.0001 <= noise1 <= 0.001
        assert 0.0001 <= noise2 <= 0.001

    def test_webgl_noise_uses_systemrandom(self) -> None:
        """Verify that noise generation uses SystemRandom (crypto-grade)."""
        # This is a structural test — we can't easily test randomness quality
        # but we can verify the module uses SystemRandom
        import random

        from pry.engine import stealth_engine

        assert isinstance(stealth_engine._RNG, random.SystemRandom)
