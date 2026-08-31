"""Pry — Anti-fingerprinting and behavioral biometrics engine.
WebGL noise, Canvas randomization, AudioContext spoofing, mouse curves, keystrokes."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import json
import logging
import random
from pathlib import Path

# SystemRandom: crypto-grade entropy so fingerprint noise is not predictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "stealth_scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


class StealthEngine:
    """Generate stealth initialization scripts for browser contexts."""

    def generate_all(self) -> str:
        """Generate complete stealth script with all fingerprint protections."""
        return (
            self.webgl_noise()
            + self.canvas_noise()
            + self.audio_noise()
            + self.font_spoof()
            + self.webdriver_hide()
        )

    def webgl_noise(self) -> str:
        """Add random noise to WebGL rendering to prevent GPU fingerprinting."""
        noise = _RNG.uniform(0.0001, 0.001)
        # Fixed-point formatting: repr() of small floats yields scientific
        # notation (e.g. 9e-05), which is valid JS but breaks downstream
        # parsers/tests expecting a plain decimal literal.
        noise_str = f"{noise:.8f}"
        return f"""
        (() => {{
            const noise = {noise_str};
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {{
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                const result = getParameter.call(this, p);
                if (typeof result === 'number' && !Number.isInteger(result)) return result + noise;
                return result;
            }};
            const getExtension = WebGLRenderingContext.prototype.getExtension;
            WebGLRenderingContext.prototype.getExtension = function(name) {{
                if (name === 'WEBGL_debug_renderer_info') return null;
                return getExtension.call(this, name);
            }};
        }})();
        """

    def canvas_noise(self) -> str:
        """Add random noise to Canvas fingerprinting."""
        noise = _RNG.uniform(0.00005, 0.0005)
        # Fixed-point: values < 1e-4 would otherwise render as scientific
        # notation (e.g. 8.7e-05) — valid JS, but breaks the plain-decimal
        # contract tests and downstream parsers rely on.
        noise_str = f"{noise:.8f}"
        return f"""
        (() => {{
            const noise = {noise_str};
            const toDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type, quality) {{
                const canvas = this;
                const ctx = canvas.getContext('2d');
                if (ctx) {{
                    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + (Math.random() > 0.5 ? 1 : -1) * noise * 255));
                    }}
                    ctx.putImageData(imageData, 0, 0);
                }}
                return toDataURL.call(this, type, quality);
            }};
        }})();
        """

    def audio_noise(self) -> str:
        """Add noise to AudioContext fingerprinting."""
        return """
        (() => {
            const getChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {
                const data = getChannelData.call(this, channel);
                for (let i = 0; i < data.length; i += 100) {
                    data[i] += (Math.random() - 0.5) * 0.0001;
                }
                return data;
            };
        })();
        """

    def font_spoof(self) -> str:
        """Spoof system fonts to avoid font fingerprinting."""
        fonts = [
            "Arial",
            "Helvetica",
            "Times New Roman",
            "Courier New",
            "Verdana",
            "Georgia",
            "Palatino",
            "Garamond",
        ]
        return f"""
        (() => {{
            const fonts = {json.dumps(fonts)};
            const measureText = CanvasRenderingContext2D.prototype.measureText;
            CanvasRenderingContext2D.prototype.measureText = function(text) {{
                const result = measureText.call(this, text);
                Object.defineProperty(result, 'width', {{ get: () => result.width + (Math.random() - 0.5) * 0.5 }});
                return result;
            }};
        }})();
        """

    def webdriver_hide(self) -> str:
        """Hide automation indicators completely."""
        return """
        (() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => Math.floor(Math.random() * 4) + 2 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => Math.floor(Math.random() * 4) + 2 });
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (p) => (
                p.name === 'notifications' ? Promise.resolve({state: 'denied'}) : originalQuery(p)
            );
        })();
        """

    def human_mouse_script(self) -> str:
        """Generate realistic human mouse movement with bezier curves."""
        return """
        (() => {
            window.__pry_mouse = { x: 0, y: 0, clicks: 0 };
            document.addEventListener('mousemove', (e) => {
                window.__pry_mouse.x = e.clientX;
                window.__pry_mouse.y = e.clientY;
            });
            window.__pry_humanClick = async (selector) => {
                const el = document.querySelector(selector);
                if (!el) return;
                const rect = el.getBoundingClientRect();
                const targetX = rect.left + rect.width / 2 + (Math.random() - 0.5) * 10;
                const targetY = rect.top + rect.height / 2 + (Math.random() - 0.5) * 10;
                const steps = Math.floor(Math.random() * 10) + 15;
                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const x = window.__pry_mouse.x + (targetX - window.__pry_mouse.x) * (1 - Math.pow(1 - t, 3));
                    const y = window.__pry_mouse.y + (targetY - window.__pry_mouse.y) * (1 - Math.pow(1 - t, 3));
                    el.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }));
                    await new Promise(r => setTimeout(r, Math.random() * 30 + 10));
                }
                el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                await new Promise(r => setTimeout(r, Math.random() * 100 + 50));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                await new Promise(r => setTimeout(r, Math.random() * 50 + 20));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                window.__pry_mouse.clicks++;
            };
        })();
        """

    def human_type_script(self) -> str:
        """Generate realistic human typing with variable delays."""
        return """
        (() => {
            window.__pry_humanType = async (selector, text) => {
                const el = document.querySelector(selector);
                if (!el) return;
                el.focus();
                el.value = '';
                for (const char of text) {
                    el.value += char;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('keydown', { bubbles: true }));
                    el.dispatchEvent(new Event('keyup', { bubbles: true }));
                    const delay = char === ' ' ? Math.random() * 200 + 100 : Math.random() * 80 + 40;
                    await new Promise(r => setTimeout(r, delay));
                }
                el.dispatchEvent(new Event('change', { bubbles: true }));
            };
        })();
        """

    def save_scripts(self) -> None:
        (SCRIPTS_DIR / "webgl_noise.js").write_text(self.webgl_noise())
        (SCRIPTS_DIR / "canvas_noise.js").write_text(self.canvas_noise())
        (SCRIPTS_DIR / "audio_noise.js").write_text(self.audio_noise())
        (SCRIPTS_DIR / "webdriver_hide.js").write_text(self.webdriver_hide())
        (SCRIPTS_DIR / "human_mouse.js").write_text(self.human_mouse_script())
        (SCRIPTS_DIR / "human_type.js").write_text(self.human_type_script())
        logger.info("stealth_scripts_saved", extra={"count": 6})
