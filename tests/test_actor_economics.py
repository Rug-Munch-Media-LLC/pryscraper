# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for factory layer 4: store-readiness linting + PPE economics."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from actor_factory.economics import (
    break_even_price_usd,
    monthly_projection,
    platform_cost_usd,
    run_economics,
)
from actor_factory.linter import lint_actor
from actor_factory.presets import ALL_PRESETS, SCRAPER_ACTOR
from actor_factory.spec import ActorSpec, InputField, PricingEvent

# ── Store-readiness linter ───────────────────────────────────────────────────


class TestStoreReadinessLint:
    def test_all_presets_pass_clean(self) -> None:
        """Every shipped preset must be store-ready with zero findings."""
        for name, spec in ALL_PRESETS.items():
            assert lint_actor(spec) == [], name

    def test_short_description_flagged(self) -> None:
        spec = ActorSpec(name="x", title="X", description="too short", version="1.0")
        assert any("description too short" in f for f in lint_actor(spec))

    def test_undocumented_input_flagged(self) -> None:
        spec = ActorSpec(
            name="x",
            title="X",
            description="d" * 100,
            version="1.0",
            inputs=(InputField(name="mystery", title="Mystery"),),
        )
        assert any("mystery" in f and "no description" in f for f in lint_actor(spec))

    def test_required_without_prefill_or_default_flagged(self) -> None:
        """Daily platform test runs DEFAULT INPUT only - required fields
        without prefill/default will fail it and get the actor deprecated."""
        spec = ActorSpec(
            name="x",
            title="X",
            description="d" * 100,
            version="1.0",
            inputs=(
                InputField(
                    name="urls",
                    title="URLs",
                    type="array",
                    editor="requestListSources",
                    required=True,
                    # no prefill, no default
                ),
            ),
        )
        assert any("daily automated test" in f for f in lint_actor(spec))

    def test_unstable_prefill_host_flagged(self) -> None:
        spec = ActorSpec(
            name="x",
            title="X",
            description="d" * 100,
            version="1.0",
            inputs=(
                InputField(
                    name="urls",
                    title="URLs",
                    type="array",
                    editor="requestListSources",
                    required=True,
                    prefill=[{"url": "https://some-flaky-shop.com"}],
                ),
            ),
        )
        assert any("not a known-stable target" in f for f in lint_actor(spec))

    def test_no_pricing_events_flagged(self) -> None:
        spec = ActorSpec(name="x", title="X", description="d" * 100, version="1.0")
        assert any("no PPE pricing events" in f for f in lint_actor(spec))

    def test_congruency_domain_noun_check(self) -> None:
        """Domain nouns (not action verbs) drive the congruency check."""
        # 'price' noun absent from copy -> flagged...
        spec = ActorSpec(
            name="pry-price-watcher",
            title="Pry Watcher",
            description="d" * 100,
            version="1.0",
            pricing_events=(
                PricingEvent(
                    name="price-captured",
                    title="Price captured",
                    description="One product price captured.",
                    price_usd=0.004,
                ),
            ),
        )
        assert any("congruency" in f for f in lint_actor(spec))
        # ...but the real preset mentions prices, so it passes.
        assert not any("congruency" in f for f in lint_actor(SCRAPER_ACTOR))


# ── PPE economics ────────────────────────────────────────────────────────────


class TestPlatformCost:
    def test_one_gb_one_hour_is_one_cu(self) -> None:
        from actor_factory.economics import COST_PER_CU_USD, WorkloadProfile

        profile = WorkloadProfile(items_per_run=3600, seconds_per_item=1.0, memory_mbytes=1024)
        assert platform_cost_usd(profile) == pytest.approx(COST_PER_CU_USD)

    def test_half_memory_half_cost(self) -> None:
        from actor_factory.economics import WorkloadProfile

        full = WorkloadProfile(items_per_run=100, seconds_per_item=2.0, memory_mbytes=2048)
        half = WorkloadProfile(items_per_run=100, seconds_per_item=2.0, memory_mbytes=1024)
        assert platform_cost_usd(half) == pytest.approx(platform_cost_usd(full) / 2)


class TestRunEconomics:
    def test_profit_formula_matches_docs(self) -> None:
        """profit = 0.8 * revenue - platform costs (Apify docs formula)."""
        from actor_factory.economics import REVENUE_SHARE, WorkloadProfile

        profile = WorkloadProfile(items_per_run=100, seconds_per_item=3.0, memory_mbytes=1024)
        price = 0.004
        result = run_economics(price_per_item_usd=price, profile=profile)
        revenue = price * 100
        costs = platform_cost_usd(profile)
        assert result["revenue_usd"] == pytest.approx(revenue, abs=1e-4)
        assert result["platform_cost_usd"] == pytest.approx(costs)
        assert result["profit_usd"] == pytest.approx(REVENUE_SHARE * revenue - costs, abs=1e-4)

    def test_scraper_preset_is_profitable_at_realistic_load(self) -> None:
        """The flagship must clear 50% margin at 512MB / ~8s per page."""
        result = run_economics(
            price_per_item_usd=0.004,
            profile=__import__(
                "actor_factory.economics", fromlist=["WorkloadProfile"]
            ).WorkloadProfile(
                items_per_run=100,
                seconds_per_item=8.0,
                memory_mbytes=512,
            ),
        )
        assert result["margin"] >= 0.5, result

    def test_underpriced_scenario_flags_negative_profit(self) -> None:
        result = run_economics(
            price_per_item_usd=0.000001,  # absurdly low
            profile=__import__(
                "actor_factory.economics", fromlist=["WorkloadProfile"]
            ).WorkloadProfile(items_per_run=10, seconds_per_item=60.0, memory_mbytes=4096),
        )
        assert result["profit_usd"] < 0


class TestBreakEven:
    def test_break_even_price_yields_target_margin(self) -> None:
        from actor_factory.economics import WorkloadProfile

        profile = WorkloadProfile(items_per_run=50, seconds_per_item=10.0, memory_mbytes=1024)
        price = break_even_price_usd(profile, target_margin=0.5)
        result = run_economics(price_per_item_usd=price, profile=profile)
        assert result["margin"] >= 0.5 - 0.01  # rounding tolerance


class TestMonthlyProjection:
    def test_scales_linearly(self) -> None:
        from actor_factory.economics import WorkloadProfile

        profile = WorkloadProfile(items_per_run=100, seconds_per_item=5.0, memory_mbytes=512)
        one_run = run_economics(price_per_item_usd=0.004, profile=profile)
        month = monthly_projection(price_per_item_usd=0.004, profile=profile, runs_per_day=10)
        assert month["runs"] == 300
        assert month["profit_usd"] == round(one_run["profit_usd"] * 300, 2)


# ── Store README quality (actor-readme best practices) ──────────────────────


class TestStoreReadmeQuality:
    @staticmethod
    def _generate(spec):
        from actor_factory.generator import generate_actor

        return generate_actor(spec, Path(tempfile.mkdtemp()))

    def test_readme_meets_300_word_minimum(self) -> None:
        """Docs: 'aim for at least 300 words'."""
        for name, spec in sorted(ALL_PRESETS.items()):
            readme = self._generate(spec).read("README.md")
            assert len(readme.split()) >= 300, f"{name}: {len(readme.split())} words"

    def test_readme_has_required_store_sections(self) -> None:
        for name, spec in sorted(ALL_PRESETS.items()):
            readme = self._generate(spec).read("README.md")
            for section in (
                "## What can this Actor do?",
                "## Tutorial",
                "## How much will it cost",
                "## Input reference",
                "## Output reference",
                "## FAQ",
                "## Support",
            ):
                assert section in readme, f"{name}: missing {section}"

    def test_readme_shows_cost_expectation_with_real_numbers(self) -> None:
        """SEO-optimized cost heading + concrete example calculation."""
        readme = self._generate(SCRAPER_ACTOR).read("README.md")
        assert "$0.0040" in readme
        assert "apify-actor-start" in readme
        assert "spending limit" in readme

    def test_readme_json_output_example_present(self) -> None:
        import json

        readme = self._generate(SCRAPER_ACTOR).read("README.md")
        json_block = readme.split("```json")[1].split("```")[0]
        parsed = json.loads(json_block)
        assert parsed["status"] == "ok"
        assert "content" in parsed

    def test_no_extra_h1_in_readme_body(self) -> None:
        """Store renders the actor name as H1 - body uses H2/H3 only."""
        for name, spec in sorted(ALL_PRESETS.items()):
            readme = self._generate(spec).read("README.md")
            h1s = [ln for ln in readme.split("\n") if ln.startswith("# ")]
            assert len(h1s) <= 1, f"{name}: {h1s}"

    def test_linter_flags_thin_readme(self) -> None:
        """The lint layer must catch what the generator guarantees."""
        from actor_factory.linter import lint_generated

        g = self._generate(SCRAPER_ACTOR)
        assert lint_generated(g.files) == []
        # simulate a thin README via a modified file map
        import tempfile

        thin_path = Path(tempfile.mkdtemp()) / "README.md"
        thin_path.write_text("# Thin\n\nNot much here.\n")
        findings = lint_generated({**g.files, "README.md": thin_path})
        assert any("too thin" in f for f in findings)


class TestMarketDrivenPresets:
    """Actors built from the Apify Store sweep (MARKET-ANALYSIS.md)."""

    def test_fourteen_presets_all_store_ready(self) -> None:
        assert len(ALL_PRESETS) == 14
        for name, spec in sorted(ALL_PRESETS.items()):
            assert lint_actor(spec) == [], name

    def test_maps_actor_uses_stable_prefill(self) -> None:
        """Google Maps URLs would flake the daily platform test."""
        spec = ALL_PRESETS["pry-maps-lead-extractor"]
        urls = next(f for f in spec.inputs if f.name == "urls")
        for entry in urls.prefill:
            url = entry.get("url", "")
            assert "google.com/maps" not in url

    def test_serp_actor_exists_with_competitive_price(self) -> None:
        spec = ALL_PRESETS["pry-serp-scraper"]
        # Market anchor: google-search-scraper has 112M runs.
        assert spec.primary_event().price_usd <= 0.005

    def test_new_actors_profitable_at_realistic_loads(self) -> None:
        from actor_factory.economics import WorkloadProfile, run_economics

        loads = {
            "pry-maps-lead-extractor": (0.005, 1024, 12),
            "pry-serp-scraper": (0.003, 512, 6),
            "pry-jobs-aggregator": (0.002, 512, 6),
            "pry-property-lister": (0.004, 1024, 10),
        }
        for name, (price, mem, secs) in loads.items():
            result = run_economics(
                price_per_item_usd=price,
                profile=WorkloadProfile(
                    items_per_run=100, seconds_per_item=secs, memory_mbytes=mem
                ),
            )
            assert result["margin"] >= 0.4, f"{name}: {result}"
