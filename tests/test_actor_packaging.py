# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Static validation of the committed ``.actor/`` package.

The flagship actor ships as a hand-curated Apify package (not the factory
generator), so nothing else pins it to the platform's packaging rules. This
module parses every surface file, asserts each reference resolves, and
enforces the Store-publication requirements recorded in
``actor_factory/linter.py`` (platform-verified 2026-08-24).

It is deliberately STATIC: no network, no docker, no actor runtime.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
ACTOR_DIR = REPO / ".actor"

# Files actor.json advertises by path, plus the standalone input schema the
# platform auto-detects and the entry point its Dockerfile runs.
SCHEMA_FILES = ("INPUT_SCHEMA.json", "output_schema.json", "dataset_schema.json")


def _load(name: str) -> dict[str, Any]:
    """Parse an ``.actor/`` file, failing loudly rather than returning None."""
    path = ACTOR_DIR / name
    assert path.is_file(), f"missing packaging file: .actor/{name}"
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def actor_json() -> dict[str, Any]:
    return _load("actor.json")


def _referenced_paths(spec: dict[str, Any]) -> list[str]:
    """Every file path actor.json promises exists, in the platform's forms."""
    refs: list[str] = []
    if isinstance(spec.get("dockerfile"), str):
        refs.append(spec["dockerfile"])
    if isinstance(spec.get("output"), str):
        refs.append(spec["output"])
    for value in (spec.get("storages") or {}).values():
        if isinstance(value, str):
            refs.append(value)
    return refs


class TestActorJson:
    def test_parses_and_has_required_fields(self, actor_json: dict[str, Any]) -> None:
        for field in ("actorSpecification", "name", "title", "version", "dockerfile"):
            assert field in actor_json, f"actor.json missing required field '{field}'"
            assert actor_json[field], f"actor.json field '{field}' is empty"
        assert actor_json["actorSpecification"] == 1

    def test_version_is_n_dot_n(self, actor_json: dict[str, Any]) -> None:
        assert re.match(r"^\d+\.\d+$", str(actor_json["version"])), (
            f"version '{actor_json['version']}' violates the Apify [N].[N] rule"
        )

    def test_every_referenced_file_exists(self, actor_json: dict[str, Any]) -> None:
        refs = _referenced_paths(actor_json)
        assert refs, "actor.json advertises no file references"
        dangling = [ref for ref in refs if not (ACTOR_DIR / ref.lstrip("./")).resolve().is_file()]
        assert not dangling, f"actor.json references missing files: {dangling}"

    def test_output_points_at_output_schema(self, actor_json: dict[str, Any]) -> None:
        assert actor_json["output"] == "./output_schema.json"


class TestInputSchema:
    def test_standalone_is_object_with_properties(self) -> None:
        schema = _load("INPUT_SCHEMA.json")
        assert schema.get("type") == "object"
        props = schema.get("properties")
        assert isinstance(props, dict)
        assert props, "input schema declares no properties"
        assert schema.get("title")

    def test_standalone_matches_embedded_actor_input(self, actor_json: dict[str, Any]) -> None:
        """The auto-detected file and the embedded spec must not drift."""
        embedded = actor_json.get("input")
        assert isinstance(embedded, dict), "actor.json should embed an input schema"
        assert _load("INPUT_SCHEMA.json") == embedded


class TestOutputSchema:
    def test_valid_and_links_dataset(self) -> None:
        out = _load("output_schema.json")
        assert out.get("actorOutputSchemaVersion") == 1
        assert out.get("title")
        props = out.get("properties") or {}
        assert props, "output schema declares no properties"
        templates = [str(p.get("template", "")) for p in props.values()]
        assert any("{{links." in t for t in templates), (
            "output schema properties lack {{links.*}} templates"
        )


class TestDatasetSchema:
    def test_valid_fields_and_view(self) -> None:
        ds = _load("dataset_schema.json")
        assert ds.get("actorSpecification") == 1
        fields = (ds.get("fields") or {}).get("properties")
        assert isinstance(fields, dict)
        assert fields, "dataset schema has no field definitions"
        assert "overview" in (ds.get("views") or {}), "missing Console 'overview' view"


class TestSchemasAreObjects:
    """Each schema surface is a valid JSON object with an identity."""

    @pytest.mark.parametrize("name", SCHEMA_FILES)
    def test_parses_to_object_with_title(self, name: str) -> None:
        doc = _load(name)
        assert isinstance(doc, dict)
        assert doc.get("title"), f"{name} has no title"


class TestDockerfileEntrypoint:
    def test_cmd_matches_existing_entry_point(self) -> None:
        spec = _load("actor.json")
        dockerfile = (ACTOR_DIR / spec["dockerfile"].lstrip("./")).read_text()
        cmd = re.search(r"^CMD\s+(\[.*\])\s*$", dockerfile, re.MULTILINE)
        assert cmd, "Dockerfile.apify declares no JSON-array CMD"
        argv = json.loads(cmd.group(1))
        script = Path(argv[-1])
        assert script.is_file(), f"CMD entry point missing: {argv[-1]}"
        # The entry point delegates to the real actor module.
        assert "pry.actors.apify_actor" in script.read_text()


class TestNoDanglingRefs:
    def test_no_schema_inlines_a_path_that_does_not_exist(self) -> None:
        """Catch any ``./name.json`` string anywhere in .actor/ that is dead."""
        known = {p.name for p in ACTOR_DIR.iterdir() if p.is_file()}
        dangling: list[str] = []
        for path in ACTOR_DIR.glob("*.json"):
            for ref in re.findall(r'"\./([A-Za-z0-9_.-]+\.json)"', path.read_text()):
                if ref not in known:
                    dangling.append(f"{path.name} -> {ref}")
        assert not dangling, f"dangling schema references: {dangling}"
