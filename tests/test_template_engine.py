# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.commerce.template_engine — template listing/lookup and the
execute_template pipeline (PryScraper patched). No live network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pry.commerce import template_engine as te


class TestListTemplates:
    def test_returns_metadata_shape(self) -> None:
        templates = te.list_templates()
        assert len(templates) >= 40
        first = templates[0]
        assert set(first) == {
            "id",
            "name",
            "description",
            "site",
            "category",
            "fields",
            "icon",
        }

    def test_sorted_by_id(self) -> None:
        ids = [t["id"] for t in te.list_templates()]
        assert ids == sorted(ids)

    def test_known_template_fields(self) -> None:
        by_id = {t["id"]: t for t in te.list_templates()}
        amazon = by_id["amazon-product"]
        assert amazon["name"] == "Amazon Product"
        assert amazon["site"] == "amazon.com"
        assert amazon["category"] == "ecommerce"
        assert [f["name"] for f in amazon["fields"]][:2] == ["title", "price"]

    def test_skips_malformed_json(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "good.json").write_text('{"name": "Good"}')
        (tmp_path / "bad.json").write_text("{not json")
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        templates = te.list_templates()
        assert [t["id"] for t in templates] == ["good"]
        assert templates[0]["name"] == "Good"
        assert templates[0]["category"] == "general"
        assert templates[0]["icon"] == "🌐"


class TestGetTemplate:
    def test_known_template(self) -> None:
        t = te.get_template("amazon-product")
        assert t is not None
        assert t["name"] == "Amazon Product"
        assert t["schema"]["base_selector"] == "#dp-container"

    def test_missing_returns_none(self) -> None:
        assert te.get_template("does-not-exist-xyz") is None

    def test_malformed_returns_none(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "broken.json").write_text("{not json")
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        assert te.get_template("broken") is None


class TestExecuteTemplate:
    @pytest.mark.asyncio
    async def test_unknown_template(self) -> None:
        result = await te.execute_template("nope-xyz", "http://x")
        assert result == {"success": False, "error": "Template not found: nope-xyz"}

    @pytest.mark.asyncio
    async def test_template_without_schema(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "empty.json").write_text('{"name": "Empty"}')
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        result = await te.execute_template("empty", "http://x")
        assert result == {"success": False, "error": "Template has no extraction schema"}

    @pytest.mark.asyncio
    async def test_scrape_failure_returns_error(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div", "fields": []}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        scraper = AsyncMock()
        scraper.scrape.return_value = {"status": "error", "error": "blocked"}
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result == {"success": False, "error": "blocked"}

    @pytest.mark.asyncio
    async def test_successful_extraction(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div.item", '
            '"fields": [{"name": "title", "selector": "h2", "type": "text"}]}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        html = "<div class='item'><h2>Widget</h2></div>"
        scraper = AsyncMock()
        scraper.scrape.return_value = {"status": "ok", "raw_html": html}
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result["success"] is True
        assert result["data"]["template_id"] == "t"
        assert result["data"]["template_name"] == "T"
        assert result["data"]["url"] == "http://x"
        assert result["data"]["items"] == [{"title": "Widget"}]
        assert result["data"]["count"] == 1
        assert "extracted_at" in result["data"]

    @pytest.mark.asyncio
    async def test_no_items_returns_warning(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div.item", '
            '"fields": [{"name": "title", "selector": "h2", "type": "text"}]}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        # HTML > 500 chars so the JS-render retry path runs; both attempts
        # return HTML with no matching items.
        html = "<p>" + ("x" * 600) + "</p>"
        scraper = AsyncMock()
        scraper.scrape.return_value = {"status": "ok", "raw_html": html}
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result["success"] is True
        assert result["data"]["items"] == []
        assert result["data"]["count"] == 0
        assert "warning" in result["data"]
        assert scraper.scrape.await_count == 2

    @pytest.mark.asyncio
    async def test_js_render_retry_uses_larger_html(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div.item", '
            '"fields": [{"name": "title", "selector": "h2", "type": "text"}]}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        small = "<p>" + ("x" * 600) + "</p>"
        big = "<div class='item'><h2>Rendered</h2></div>" + ("y" * 600)
        scraper = AsyncMock()
        scraper.scrape.side_effect = [
            {"status": "ok", "raw_html": small},
            {"status": "ok", "raw_html": big},
        ]
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result["data"]["items"] == [{"title": "Rendered"}]

    @pytest.mark.asyncio
    async def test_tier2_js_render_when_first_scrape_fails(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div.item", '
            '"fields": [{"name": "title", "selector": "h2", "type": "text"}]}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        html = "<div class='item'><h2>FromJS</h2></div>"
        scraper = AsyncMock()
        scraper.scrape.side_effect = [
            {"status": "error", "error": "cf"},
            {"status": "ok", "raw_html": html},
        ]
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result["data"]["items"] == [{"title": "FromJS"}]
        assert scraper.scrape.await_count == 2

    @pytest.mark.asyncio
    async def test_both_tiers_fail_returns_error(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "t.json").write_text(
            '{"name": "T", "schema": {"base_selector": "div", "fields": []}}'
        )
        monkeypatch.setattr(te, "TEMPLATES_DIR", tmp_path)
        scraper = AsyncMock()
        scraper.scrape.side_effect = [
            {"status": "error", "error": "tier1"},
            {"status": "error", "error": "tier2"},
        ]
        with patch("pry.engine.scraper.PryScraper", return_value=scraper):
            result = await te.execute_template("t", "http://x")
        assert result == {"success": False, "error": "tier1"}
