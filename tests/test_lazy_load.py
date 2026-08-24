# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for lazy load detection."""

from pry.engine.lazy_load import (
    detect_lazy_loading,
    generate_load_more_script,
    generate_scroll_script,
)


def test_detect_lazy_images() -> None:
    html = '<img src="photo.jpg" loading="lazy" />'
    result = detect_lazy_loading(html)
    assert result["lazy_images"] is True


def test_detect_infinite_scroll() -> None:
    html = '<div id="infinite-scroll-container">'
    result = detect_lazy_loading(html)
    assert result["infinite_scroll"] is True


def test_detect_intersection_observer() -> None:
    html = "<script>new IntersectionObserver()</script>"
    result = detect_lazy_loading(html)
    assert result["intersection_observer"] is True


def test_scroll_script_generated() -> None:
    script = generate_scroll_script(max_scrolls=3, delay_ms=500)
    assert "scrollTo" in script
    assert "max_scrolls" not in script  # The JS variable
    assert "3" in script  # The max_scrolls value


def test_load_more_script() -> None:
    script = generate_load_more_script(max_clicks=5)
    assert "click" in script
    assert "load more" in script.lower()
