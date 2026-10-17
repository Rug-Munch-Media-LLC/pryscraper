"""Marketplace run path: preset resolution, billing order, failure propagation.

No network: the scraper and template executor are patched.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from actor_factory.presets import ALL_PRESETS
from pry.api.routers.commerce import marketplace as router_mod
from pry.commerce import actor_marketplace as am

PRICE = 0.003


def _preset(processor: bool) -> str:
    """A real preset id, with or without a processor."""
    for name, spec in sorted(ALL_PRESETS.items()):
        if (spec.processor is not None) is processor:
            return name
    raise AssertionError(f"no preset with processor={processor}")


class _FakeScraper:
    async def scrape(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "ok", "content": "hello world", "raw_html": "<p>hi</p>"}


class _Base:
    @pytest.fixture(autouse=True)
    def _isolated_store(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setattr(am, "ACTOR_DIR", tmp_path)
        monkeypatch.setattr("pry.engine.scraper.PryScraper", _FakeScraper)
        self.market = am.ActorMarketplace()

    def _reload(self) -> am.ActorMarketplace:
        return am.ActorMarketplace()


class TestPresetResolution(_Base):
    async def test_run_resolves_preset_without_persisting(self, tmp_path) -> None:
        preset = _preset(processor=True)

        result = await self.market.run(preset, {"url": "https://example.com"})

        assert result["success"] is True
        assert result["actor_id"] == preset
        assert result["engine"] == ALL_PRESETS[preset].processor
        assert list(tmp_path.glob("*.json")) == [], "read-only fallback must not write"

    async def test_rest_handler_resolves_preset(self) -> None:
        preset = _preset(processor=True)

        result = await router_mod.run_actor(preset, {"url": "https://example.com"})

        assert result["success"] is True
        assert result["actor_id"] == preset

    async def test_preset_without_processor_is_unpriced(self) -> None:
        preset = _preset(processor=False)

        result = await self.market.run(preset, {"url": "https://example.com"})

        assert result["success"] is False
        assert result["code"] == "requires_processor"

    async def test_unknown_actor_is_not_found(self) -> None:
        result = await self.market.run("no-such-actor-xyz", {"url": "https://example.com"})

        assert result["success"] is False
        assert result["code"] == "not_found"


class TestBillingOrder(_Base):
    async def test_failed_template_does_not_bill(self) -> None:
        actor = self.market.create(
            "broken", "d", template_id="does-not-exist-xyz", price_per_run=PRICE
        )

        result = await self.market.run(actor.actor_id, {"url": "https://example.com"})

        assert result["success"] is False
        assert result["code"] == "template_not_found"
        stored = self._reload().actors[actor.actor_id]
        assert stored.run_count == 0
        assert stored.revenue_usd == 0.0

    async def test_template_exception_does_not_bill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        actor = self.market.create("boom", "d", template_id="amazon-product", price_per_run=PRICE)

        async def _explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("extractor exploded")

        monkeypatch.setattr("pry.commerce.template_engine.execute_template", _explode)
        result = await self.market.run(actor.actor_id, {"url": "https://example.com"})

        assert result["success"] is False
        assert result["code"] == "execution_error"
        assert "extractor exploded" in result["error"]
        assert self._reload().actors[actor.actor_id].revenue_usd == 0.0

    async def test_missing_url_does_not_bill(self) -> None:
        actor = self.market.create("nourl", "d", template_id="amazon-product", price_per_run=PRICE)

        result = await self.market.run(actor.actor_id, {})

        assert result["success"] is False
        assert result["code"] == "invalid_input"
        assert self._reload().actors[actor.actor_id].revenue_usd == 0.0

    async def test_successful_template_bills_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        actor = self.market.create("works", "d", template_id="amazon-product", price_per_run=PRICE)

        async def _ok(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"success": True, "data": {"items": [{"title": "x"}], "count": 1}}

        monkeypatch.setattr("pry.commerce.template_engine.execute_template", _ok)
        result = await self.market.run(actor.actor_id, {"url": "https://example.com"})

        assert result["success"] is True
        stored = self._reload().actors[actor.actor_id]
        assert stored.run_count == 1
        assert stored.revenue_usd == pytest.approx(PRICE)


class TestNoTemplate(_Base):
    async def test_actor_without_template_fails_and_keeps_revenue(self) -> None:
        actor = self.market.create("empty", "d", price_per_run=PRICE)

        result = await self.market.run(actor.actor_id, {"url": "https://example.com"})

        assert result["success"] is False
        assert result["code"] == "no_template"
        stored = self._reload().actors[actor.actor_id]
        assert stored.run_count == 0
        assert stored.revenue_usd == 0.0

    async def test_router_maps_failure_to_http_status(self) -> None:
        actor = self.market.create("empty", "d", price_per_run=PRICE)

        with pytest.raises(HTTPException) as excinfo:
            await router_mod.run_actor(actor.actor_id, {"url": "https://example.com"})

        assert excinfo.value.status_code == 409
