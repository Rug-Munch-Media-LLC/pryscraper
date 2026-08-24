# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
"""Pry — lazy load and infinite scroll handling."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def detect_lazy_loading(html: str) -> dict[str, Any]:
    """Detect lazy loading patterns in HTML."""
    result: dict[str, Any] = {
        "lazy_images": False,
        "lazy_frames": False,
        "infinite_scroll": False,
        "load_more": False,
        "intersection_observer": False,
    }

    # Check for lazy loading images
    if re.search(r'loading=["\']lazy["\']', html, re.IGNORECASE):
        result["lazy_images"] = True

    # Check for lazy loading iframes
    if re.search(r'<iframe[^>]*loading=["\']lazy["\']', html, re.IGNORECASE):
        result["lazy_frames"] = True

    # Check for infinite scroll
    if re.search(r"infinite[_-]?scroll|infinitescroll", html, re.IGNORECASE):
        result["infinite_scroll"] = True

    # Check for "load more" buttons
    if re.search(r"load[_-]?more|show[_-]?more|see[_-]?more", html, re.IGNORECASE):
        result["load_more"] = True

    # Intersection Observer API
    if re.search(r"IntersectionObserver", html):
        result["intersection_observer"] = True

    return result


def generate_scroll_script(max_scrolls: int = 5, delay_ms: int = 1000) -> str:
    """Generate JavaScript to scroll through lazy-loaded content.

    Returns JS that scrolls the page in steps, waiting for content to load.
    """
    return f"""
    (async () => {{
        const delay = ms => new Promise(r => setTimeout(r, ms));
        let prevHeight = document.body.scrollHeight;
        let scrolls = 0;
        while (scrolls < {max_scrolls}) {{
            window.scrollTo(0, document.body.scrollHeight);
            await delay({delay_ms});
            const newHeight = document.body.scrollHeight;
            if (newHeight === prevHeight) break;
            prevHeight = newHeight;
            scrolls++;
        }}
        // Scroll back to top
        window.scrollTo(0, 0);
        await delay(200);
    }})();
    """


def generate_load_more_script(max_clicks: int = 10, delay_ms: int = 1500) -> str:
    """Generate JavaScript to click 'Load More' buttons.

    Finds buttons with text containing 'load more', 'show more', etc.
    """
    return f"""
    (async () => {{
        const delay = ms => new Promise(r => setTimeout(r, ms));
        const patterns = ['load more', 'show more', 'see more', 'view more', 'load additional'];
        let clicks = 0;
        while (clicks < {max_clicks}) {{
            let clicked = false;
            for (const pattern of patterns) {{
                const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                for (const btn of buttons) {{
                    if (btn.textContent.toLowerCase().includes(pattern)) {{
                        btn.click();
                        clicked = true;
                        await delay({delay_ms});
                        break;
                    }}
                }}
                if (clicked) break;
            }}
            if (!clicked) break;
            clicks++;
        }}
    }})();
    """
