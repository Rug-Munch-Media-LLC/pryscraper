"""Branch coverage for actor marketplace load/save and execution failures."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pry.commerce import actor_marketplace as am


@pytest.fixture
def market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(am, "ACTOR_DIR", tmp_path)
    return am.ActorMarketplace()


def test_preset_specs_empty_when_factory_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = types.ModuleType("actor_factory.presets")
    monkeypatch.setitem(sys.modules, "actor_factory.presets", broken)
    assert am.preset_specs() == {}


def test_load_skips_corrupt_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(am, "ACTOR_DIR", tmp_path)
    (tmp_path / "bad.json").write_text("{not json")
    good = {
        "actor_id": "a1",
        "name": "n",
        "description": "d",
        "visibility": "public",
        "tags": ["web"],
        "run_count": 2,
        "revenue_usd": 0.0,
    }
    (tmp_path / "a1.json").write_text(json.dumps(good))

    loaded = am.ActorMarketplace()

    assert list(loaded.actors) == ["a1"]
    assert loaded.actors["a1"].visibility is am.ActorVisibility.PUBLIC
    assert loaded.list(visibility="public")[0]["run_count"] == 2


def test_save_failure_keeps_actor_registered(market, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, *_a, **_k):
        raise OSError("read-only fs")

    monkeypatch.setattr(Path, "write_text", boom)
    actor = market.create("n", "d")

    assert market.actors[actor.actor_id] is actor
    assert actor.visibility is am.ActorVisibility.PRIVATE


def test_run_unknown_actor_returns_not_found(market) -> None:
    assert asyncio.run(market.run("nope")) == {
        "success": False,
        "code": "not_found",
        "error": "Actor not found: nope",
    }


def test_run_preset_without_processor_is_rejected(market, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(category="web", title="P", description="d", processor=None)
    monkeypatch.setattr(am, "preset_specs", lambda: {"pres": spec})

    out = asyncio.run(market.run("pres", {"url": "https://x.test"}))

    assert out["code"] == "requires_processor"
    assert out["error"] == "Actor 'pres' is unpriced (no processor)"


def test_run_requires_url_before_template(market) -> None:
    actor = market.create("n", "d")
    assert asyncio.run(market.run(actor.actor_id))["code"] == "invalid_input"


def test_run_actor_without_template_fails_closed(market) -> None:
    actor = market.create("n", "d")
    out = asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))
    assert out["code"] == "no_template"
    assert out["error"] == f"Actor '{actor.actor_id}' has no template to execute"


def test_template_exception_becomes_execution_error(
    market, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = market.create("n", "d", template_id="tpl")

    async def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr("pry.commerce.template_engine.execute_template", boom)
    out = asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))

    assert out == {"success": False, "code": "execution_error", "error": "Template failed: boom"}


def test_template_not_found_is_classified(market, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = market.create("n", "d", template_id="tpl")

    async def missing(*_a, **_k):
        return {"success": False, "error": "Template not found: tpl"}

    monkeypatch.setattr("pry.commerce.template_engine.execute_template", missing)
    out = asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))
    assert out["code"] == "template_not_found"


def test_empty_template_result_is_not_billed(market, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = market.create("n", "d", template_id="tpl", price_per_run=1.0)

    async def empty(*_a, **_k):
        return {"success": True, "data": {}}

    monkeypatch.setattr("pry.commerce.template_engine.execute_template", empty)
    out = asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))

    assert out["code"] == "empty_result"
    assert actor.run_count == 0
    assert actor.revenue_usd == 0.0


def test_successful_run_bills_once(market, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = market.create("n", "d", template_id="tpl", price_per_run=0.5)

    async def ok(*_a, **_k):
        return {"success": True, "data": {"title": "x"}}

    monkeypatch.setattr("pry.commerce.template_engine.execute_template", ok)
    out = asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))

    assert out["data"] == {"title": "x"}
    assert actor.run_count == 1
    assert actor.revenue_usd == 0.5


def test_zero_price_run_still_counts(market, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = market.create("n", "d", template_id="tpl")

    async def ok(*_a, **_k):
        return {"success": True, "data": {"x": 1}}

    monkeypatch.setattr("pry.commerce.template_engine.execute_template", ok)
    asyncio.run(market.run(actor.actor_id, {"url": "https://x.test"}))

    assert actor.run_count == 1
    assert actor.revenue_usd == 0.0


def test_preset_scrape_paths(market, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(category="web", title="P", description="d", processor="engine")
    monkeypatch.setattr(am, "preset_specs", lambda: {"pres": spec})

    async def ok(_url, _opts):
        return {"status": "ok", "raw_html": "<p>x</p>"}

    monkeypatch.setattr(am._scraper, "scrape", ok)
    out = asyncio.run(market.run("pres", {"url": "https://x.test"}))
    assert out["data"]["content"] == "<p>x</p>"
    assert out["engine"] == "engine"

    async def raises(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(am._scraper, "scrape", raises)
    assert asyncio.run(market.run("pres", {"url": "https://x.test"}))["code"] == "scrape_failed"


def test_preset_scrape_error_status(market, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(category="web", title="P", description="d", processor="engine")
    monkeypatch.setattr(am, "preset_specs", lambda: {"pres": spec})

    async def blocked(_url, _opts):
        return {"status": "error", "error": "blocked"}

    monkeypatch.setattr(am._scraper, "scrape", blocked)
    out = asyncio.run(market.run("pres", {"url": "https://x.test"}))
    assert out == {"success": False, "code": "scrape_failed", "error": "blocked"}
