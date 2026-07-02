# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraper templates."""

from template_engine import get_template, list_templates


def test_list_templates() -> None:
    templates = list_templates()
    assert len(templates) >= 40  # At least 40 templates
    assert any("amazon" in t["id"] for t in templates)
    assert any("linkedin" in t["id"] for t in templates)
    assert any("github" in t["id"] for t in templates)


def test_get_amazon_template() -> None:
    t = get_template("amazon-product")
    assert t is not None
    assert t["name"] == "Amazon Product"
    assert "schema" in t
    assert len(t["schema"]["fields"]) > 5


def test_get_linkedin_template() -> None:
    t = get_template("linkedin-profile")
    assert t is not None
    assert "profile" in t["name"].lower()


def test_get_nonexistent() -> None:
    t = get_template("nonexistent-site-12345")
    assert t is None


def test_templates_have_categories() -> None:
    templates = list_templates()
    categories = {t["category"] for t in templates}
    assert "ecommerce" in categories
    assert "professional" in categories


def test_templates_have_icons() -> None:
    templates = list_templates()
    for t in templates:
        assert t.get("icon"), f"Template {t['id']} missing icon"
