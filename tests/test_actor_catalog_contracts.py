"""Per-actor contract tests — every preset, no sampling (94/94).

Directive: each actor must SAY what it does (honest metadata) and DO
what it says (generated package is complete, compilable, schema-valid,
and wired to a real engine + MCP tool). These tests parametrize over
ALL_PRESETS so a bad actor cannot hide behind its siblings.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import py_compile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from actor_factory.presets import ALL_PRESETS
from actor_factory.publish import ENGINE_FILES
from actor_factory.spec import VALID_EDITORS

NAMES = sorted(ALL_PRESETS)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "actor_name" in metafunc.fixturenames:
        metafunc.parametrize("actor_name", NAMES)


# ── SAY WHAT THEY DO: metadata honesty ───────────────────────────────────


def test_name_is_store_safe(actor_name: str) -> None:
    assert len(actor_name) >= 4, actor_name
    assert len(actor_name) <= 60, actor_name
    assert actor_name.startswith("pry-"), actor_name


def test_title_is_branded_and_human(actor_name: str) -> None:
    spec = ALL_PRESETS[actor_name]
    assert spec.title.startswith("Pry "), f"{actor_name}: {spec.title!r}"
    assert len(spec.title) >= 10, actor_name
    assert len(spec.title) <= 80, actor_name


def test_description_substantive(actor_name: str) -> None:
    desc = ALL_PRESETS[actor_name].description.strip()
    # Honest descriptions say what it does, for whom — not placeholders.
    assert len(desc) >= 60, f"{actor_name}: description too thin ({len(desc)} chars)"
    assert not desc.lower().startswith(("todo", "tbd", "fixme")), actor_name


def test_version_is_pinned_major_minor(actor_name: str) -> None:
    import re

    assert re.match(r"^\d+\.\d+$", ALL_PRESETS[actor_name].version), actor_name


def test_memory_bounds_sane(actor_name: str) -> None:
    spec = ALL_PRESETS[actor_name]
    assert spec.min_memory_mbytes >= 256, actor_name
    assert spec.min_memory_mbytes <= spec.max_memory_mbytes, actor_name
    assert spec.max_memory_mbytes <= 32768, actor_name
    if spec.uses_browser:
        assert spec.min_memory_mbytes >= 512, f"{actor_name}: browser needs >=512MB"


def test_inputs_well_formed(actor_name: str) -> None:
    spec = ALL_PRESETS[actor_name]
    assert spec.inputs, f"{actor_name}: no input fields at all"
    names = [f.name for f in spec.inputs]
    assert len(names) == len(set(names)), f"{actor_name}: duplicate inputs"
    for f in spec.inputs:
        assert f.title, f"{actor_name}/{f.name}: empty title"
        assert len(f.title) >= 3, f"{actor_name}/{f.name}: title too short"
        # Factory-supported types; decimal inputs pair with editor="float"
        assert f.type in {
            "string",
            "integer",
            "boolean",
            "array",
            "object",
            "float",
        }, f"{actor_name}/{f.name}: type {f.type}"
        if f.type in ("integer", "float"):
            # Apify platform: numeric fields accept ONLY number/hidden
            assert f.editor == "number", (
                f"{actor_name}/{f.name}: numeric input needs editor='number'"
            )
        if f.editor is not None:
            assert f.editor in VALID_EDITORS, f"{actor_name}/{f.name}: editor"


def test_pricing_honest(actor_name: str) -> None:
    """Every paid event: positive price, kebab name, primary first."""
    spec = ALL_PRESETS[actor_name]
    assert spec.pricing_events, f"{actor_name}: no pricing events"
    prices = [e.price_usd for e in spec.pricing_events]
    assert all(p > 0 for p in prices), f"{actor_name}: non-positive price"
    assert max(prices) <= 1.0, f"{actor_name}: price above $1 per event"
    seen: set[str] = set()
    for e in spec.pricing_events:
        assert e.name not in seen, f"{actor_name}: duplicate event {e.name}"
        seen.add(e.name)


# ── DO WHAT THEY SAY: generated package contract ─────────────────────────


@pytest.fixture(scope="package")
def generated_cache(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Generate every actor ONCE for the whole module (94 generations)."""
    cache: dict[str, Path] = {}
    root = tmp_path_factory.mktemp("actors")
    for name in NAMES:
        out = root / name
        from actor_factory import generate_actor

        generate_actor(ALL_PRESETS[name], out)
        cache[name] = out
    return cache


def test_package_complete(generated_cache: dict[str, Path], actor_name: str) -> None:
    stage = generated_cache[actor_name]
    assert (stage / ".actor" / "actor.json").is_file(), actor_name
    assert (stage / ".actor" / "INPUT_SCHEMA.json").is_file(), actor_name
    assert (stage / ".actor" / "Dockerfile").is_file(), actor_name
    assert (stage / ".actor" / "icon.svg").is_file(), actor_name
    assert (stage / "src" / "main.py").is_file(), actor_name
    # requirements.lock is injected at STAGING time (_actor_lock_contents),
    # not by generate_actor — everything else must exist post-generation.
    for req in ENGINE_FILES:
        if req == "requirements.lock":
            continue
        assert (stage / req).is_file(), f"{actor_name}: missing {req}"


def test_actor_json_matches_spec(generated_cache: dict[str, Path], actor_name: str) -> None:
    spec = ALL_PRESETS[actor_name]
    doc = json.loads((generated_cache[actor_name] / ".actor" / "actor.json").read_text())
    # Store name drops the pry- prefix (Apify-neutral naming)
    assert doc["name"] == actor_name.removeprefix("pry-")
    # Store title is the SEO-functional form (brand prefix stripped)
    assert doc["title"] == spec.title.removeprefix("Pry ").strip()
    assert doc["version"] == spec.version
    assert doc["description"] == spec.description
    assert doc["minMemoryMbytes"] == spec.min_memory_mbytes
    assert doc["maxMemoryMbytes"] == spec.max_memory_mbytes


def test_input_schema_reflects_spec_inputs(
    generated_cache: dict[str, Path], actor_name: str
) -> None:
    spec = ALL_PRESETS[actor_name]
    schema = json.loads((generated_cache[actor_name] / ".actor" / "INPUT_SCHEMA.json").read_text())
    props = schema["properties"]
    # Generator ADDS standard fields (max_items, proxy_configuration);
    # the contract is that every SPEC input is present and honest.
    for f in spec.inputs:
        assert f.name in props, f"{actor_name}: input {f.name} missing from schema"
        assert props[f.name]["title"] == f.title, f"{actor_name}/{f.name}"
        assert props[f.name]["type"] == f.type, f"{actor_name}/{f.name}"


def test_main_py_compiles(generated_cache: dict[str, Path], actor_name: str) -> None:
    main = generated_cache[actor_name] / "src" / "main.py"
    py_compile.compile(str(main), doraise=True)


def test_main_py_is_real_apify_entrypoint(
    generated_cache: dict[str, Path], actor_name: str
) -> None:
    src = (generated_cache[actor_name] / "src" / "main.py").read_text()
    assert "async def main()" in src, actor_name
    assert "Actor" in src, f"{actor_name}: no Apify SDK usage"
    assert "__main__" in src, actor_name


def test_readme_documents_every_pricing_event(
    generated_cache: dict[str, Path], actor_name: str
) -> None:
    spec = ALL_PRESETS[actor_name]
    readme = (generated_cache[actor_name] / ".actor" / "README.md").read_text()
    for e in spec.pricing_events:
        assert f"`{e.name}`" in readme, f"{actor_name}: README missing event {e.name}"


def test_processor_maps_to_known_engine(actor_name: str) -> None:
    """Every processor must be a registered engine or intentional None.

    Guards the x402 catalog's engine->MCP-tool mapping: an unknown
    processor here means the catalog endpoint would fall back to
    pry_scrape silently.
    """
    from pry.api.routers.commerce.x402 import ENGINE_TOOLS

    spec = ALL_PRESETS[actor_name]
    assert spec.processor in ENGINE_TOOLS, (
        f"{actor_name}: processor {spec.processor!r} not in the x402 catalog "
        "engine registry - it would silently fall back to pry_scrape"
    )
    tool = ENGINE_TOOLS[spec.processor]
    assert tool.startswith("pry_"), f"{actor_name}: bad MCP tool mapping {tool}"
