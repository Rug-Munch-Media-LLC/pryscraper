# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the Apify Actor Factory.

Three layers, per ACTOR-FACTORY.md methodology:
1. Spec layer - Apify actor.json v1 rules enforced by ActorSpec validation.
2. Generation layer - deterministic, complete, valid .actor packages.
3. Runtime layer - PPE billing behaviour against a MOCKED Actor SDK:
   charging per item, spending-limit stops, abort flushing, error items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from actor_factory.generator import generate_actor, validate_generated
from actor_factory.presets import ALL_PRESETS, MONITOR_ACTOR, SCRAPER_ACTOR
from actor_factory.runner import ActorRunConfig, PPEScraperRunner
from actor_factory.spec import ActorSpec, InputField, PricingEvent

if TYPE_CHECKING:
    from pathlib import Path

# ── Layer 1: spec validation ─────────────────────────────────────────────────


class TestSpecValidation:
    def test_version_must_be_major_minor(self) -> None:
        with pytest.raises(ValueError, match=r"\[Number\]\.\[Number\]"):
            ActorSpec(name="x", title="X", description="d", version="1.0.0")

    def test_name_charset(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            ActorSpec(name="My Actor", title="X", description="d")

    def test_synthetic_event_rejected(self) -> None:
        with pytest.raises(ValueError, match="synthetic"):
            PricingEvent(
                name="apify-actor-start",
                title="t",
                description="d",
                price_usd=0.01,
            )

    def test_event_price_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            PricingEvent(name="page", title="t", description="d", price_usd=0)

    def test_browser_memory_floor(self) -> None:
        with pytest.raises(ValueError, match="512"):
            ActorSpec(
                name="x",
                title="X",
                description="d",
                min_memory_mbytes=256,
                max_memory_mbytes=1024,
            )

    def test_duplicate_inputs_rejected(self) -> None:
        f = InputField(name="urls", title="URLs", type="array")
        with pytest.raises(ValueError, match="duplicate"):
            ActorSpec(name="x", title="X", description="d", inputs=(f, f))

    def test_invalid_editor_rejected(self) -> None:
        with pytest.raises(ValueError, match="editor"):
            InputField(name="a", title="A", editor="magic-wand").to_schema()

    def test_primary_event_is_first(self) -> None:
        e1 = PricingEvent(name="alpha", title="A", description="d", price_usd=0.01)
        e2 = PricingEvent(name="beta", title="B", description="d", price_usd=0.02)
        spec = ActorSpec(name="x", title="X", description="d", pricing_events=(e1, e2))
        assert spec.primary_event().name == "alpha"


# ── Layer 2: generation ──────────────────────────────────────────────────────


class TestGeneration:
    def test_all_presets_generate_valid_packages(self, tmp_path: Path) -> None:
        for name, spec in ALL_PRESETS.items():
            out = tmp_path / name
            generated = generate_actor(spec, out)
            assert validate_generated(generated.files) == [], name

    def test_generation_is_deterministic(self, tmp_path: Path) -> None:
        g1 = generate_actor(SCRAPER_ACTOR, tmp_path / "a")
        g2 = generate_actor(SCRAPER_ACTOR, tmp_path / "b")
        for fname in g1.files:
            assert g1.read(fname) == g2.read(fname), fname

    def test_actor_json_spec_fields(self, tmp_path: Path) -> None:
        g = generate_actor(SCRAPER_ACTOR, tmp_path)
        spec = json.loads(g.read("actor.json"))
        assert spec["actorSpecification"] == 1
        assert spec["version"] == "1.0"
        assert spec["dockerfile"] == "./Dockerfile"
        assert spec["minMemoryMbytes"] <= spec["maxMemoryMbytes"]
        assert spec["input"]["schemaVersion"] == 1
        assert "urls" in spec["input"]["properties"]

    def test_input_schema_file_matches_embedded(self, tmp_path: Path) -> None:
        g = generate_actor(SCRAPER_ACTOR, tmp_path)
        embedded = json.loads(g.read("actor.json"))["input"]
        standalone = json.loads(g.read("INPUT_SCHEMA.json"))
        # standalone may omit empty required; compare properties + version
        assert standalone["properties"] == embedded["properties"]
        assert standalone.get("required") == embedded.get("required")

    def test_readme_documents_pricing_events(self, tmp_path: Path) -> None:
        g = generate_actor(MONITOR_ACTOR, tmp_path)
        readme = g.read("README.md")
        assert "`page-checked`" in readme
        assert "`change-detected`" in readme
        assert "$0.0010" in readme

    def test_dockerfile_uses_pinned_lock(self, tmp_path: Path) -> None:
        g = generate_actor(SCRAPER_ACTOR, tmp_path)
        dockerfile = g.read("Dockerfile")
        assert "FROM apify/actor-python" in dockerfile
        assert "requirements.lock" in dockerfile
        assert "apify-sdk" in dockerfile


# ── Layer 3: PPE runtime against a mocked Actor ──────────────────────────────


@dataclass
class FakeChargeResult:
    event_charge_limit_reached: bool = False
    charged_count: int = 1


@dataclass
class FakeActor:
    """Mock of the Apify SDK Actor surface used by PPEScraperRunner."""

    input_data: dict[str, Any] = field(default_factory=dict)
    fail_after_pushes: int | None = None  # simulate user spending limit
    pushes: list[dict[str, Any]] = field(default_factory=list)
    charge_calls: list[str] = field(default_factory=list)
    handlers: dict = field(default_factory=dict)
    exited: bool = False

    async def get_input(self) -> dict[str, Any]:
        return self.input_data

    async def push_data(
        self, item: dict[str, Any], event_name: str | None = None
    ) -> FakeChargeResult:
        # Platform semantics (docs): once the user spending limit is reached,
        # pushData STOPS pushing - the boundary item is not saved.
        if self.fail_after_pushes is not None and len(self.pushes) >= self.fail_after_pushes:
            return FakeChargeResult(event_charge_limit_reached=True)
        self.pushes.append(item)
        if event_name:
            self.charge_calls.append(event_name)
        return FakeChargeResult()

    async def charge(self, event_name: str) -> FakeChargeResult:
        self.charge_calls.append(event_name)
        return FakeChargeResult()

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    async def exit(self) -> None:
        self.exited = True

    async def __aenter__(self) -> FakeActor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class TestPPERuntime:
    @staticmethod
    def _runner(actor: FakeActor, urls: list[str]) -> PPEScraperRunner:
        actor.input_data = {"urls": urls, "output_format": "markdown"}
        runner = PPEScraperRunner(
            config=ActorRunConfig(primary_event="page-scraped"),
            actor_module=actor,
        )

        # Stub the expensive part: deterministic items without network.
        async def fake_process(url: str, options: dict) -> dict:
            return {
                "url": url,
                "status": "ok",
                "content": "content",
                "scraped_at": "2026-08-23T00:00:00+00:00",
            }

        runner.process_url = fake_process  # type: ignore[method-assign]
        return runner

    @pytest.mark.asyncio
    async def test_charges_primary_event_per_item(self) -> None:
        actor = FakeActor()
        stats = await self._runner(actor, ["http://e.com/1", "http://e.com/2"]).run()
        assert actor.charge_calls == ["page-scraped", "page-scraped"]
        assert stats.pushed_ok == 2
        assert stats.limit_reached is False

    @pytest.mark.asyncio
    async def test_stops_on_user_spending_limit(self) -> None:
        """Docs: finish the run once event_charge_limit_reached is true."""
        actor = FakeActor(fail_after_pushes=2)
        stats = await self._runner(actor, [f"http://e.com/{i}" for i in range(10)]).run()
        # Platform refuses the boundary item: only 2 items were within budget,
        # the 3rd push attempt is rejected without saving.
        assert len(actor.pushes) == 2
        assert stats.limit_reached is True
        assert stats.pushed_ok == 2

    @pytest.mark.asyncio
    async def test_error_items_still_pushed_and_charged(self) -> None:
        """Docs: charge for invalid input; return error items transparently."""
        actor = FakeActor()
        runner = PPEScraperRunner(
            config=ActorRunConfig(primary_event="page-scraped"), actor_module=actor
        )
        actor.input_data = {"urls": ["http://e.com/dead"]}

        async def failing_process(url: str, options: dict) -> dict:
            raise RuntimeError("connection refused")

        runner.process_url = failing_process  # type: ignore[method-assign]
        stats = await runner.run()
        assert len(actor.pushes) == 1
        assert actor.pushes[0]["status"] == "error"
        assert "processing_failed" in actor.pushes[0]["error"]
        assert actor.charge_calls == ["page-scraped"]  # billed for work done
        assert stats.pushed_error == 1

    @pytest.mark.asyncio
    async def test_request_list_sources_input_normalized(self) -> None:
        actor = FakeActor()
        actor.input_data = {
            "urls": [{"url": "http://e.com/a"}, {"url": "not-a-url"}],
        }
        runner = PPEScraperRunner(
            config=ActorRunConfig(primary_event="page-scraped"), actor_module=actor
        )

        async def fake_process(url: str, options: dict) -> dict:
            return {"url": url, "status": "ok"}

        runner.process_url = fake_process  # type: ignore[method-assign]
        await runner.run()
        assert [p["url"] for p in actor.pushes] == ["http://e.com/a"]

    def test_aborting_handler_flushes_pending(self) -> None:
        runner = PPEScraperRunner(
            config=ActorRunConfig(primary_event="page-scraped"), actor_module=FakeActor()
        )
        runner._pending = [{"url": "http://e.com/x"}]
        runner.on_aborting()
        assert runner.stats.aborted_flushed == 1
        assert runner._pending == []

    @pytest.mark.asyncio
    async def test_aborting_handler_registered_on_run(self) -> None:
        actor = FakeActor()
        await self._runner(actor, []).run()
        assert "aborting" in actor.handlers

    @pytest.mark.asyncio
    async def test_max_items_runaway_cap(self) -> None:
        actor = FakeActor()
        runner = self._runner(actor, [f"http://e.com/{i}" for i in range(50)])
        runner.config.max_items = 5
        await runner.run()
        assert len(actor.pushes) == 5
