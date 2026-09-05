"""— Apify Actor Factory: package generator.

Renders an :class:`ActorSpec` into a complete, deployable ``.actor``
package: actor.json, Dockerfile, INPUT_SCHEMA.json, README.md and
``src/main.py`` wired to the shared PPE runtime (``actor_factory.runner``).

Generated packages follow Apify's documented layout exactly:
- actor.json v1 spec (lowercase ``dockerfile``, [N].[N] version)
- INPUT_SCHEMA.json auto-detected at .actor/INPUT_SCHEMA.json
- Dockerfile based on apify/actor-python with pinned lock

Rendering is split across cohesive modules:
- ``generator_templates`` - raw file templates (main.py, Dockerfile)
- ``generator_readme``    - README / store-copy rendering

Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from actor_factory.generator_readme import (
    _default_output_format,
    _render_readme,
)
from actor_factory.generator_templates import DOCKERFILE_TEMPLATE, MAIN_TEMPLATE

if TYPE_CHECKING:
    from actor_factory.spec import ActorSpec

__all__ = [
    "DOCKERFILE_TEMPLATE",
    "MAIN_TEMPLATE",
    "GeneratedActor",
    "generate_actor",
    "to_jsonable",
    "validate_generated",
]


@dataclass(frozen=True)
class GeneratedActor:
    """Paths of one generated .actor package."""

    out_dir: Path
    files: dict[str, Path]

    def read(self, name: str) -> str:
        return self.files[name].read_text()


def generate_actor(spec: ActorSpec, out_dir: Path) -> GeneratedActor:
    """Render ``spec`` into ``out_dir/.actor`` + ``src/main.py``.

    Returns the written file map. Deterministic: same spec + same factory
    version => byte-identical output (enforced by tests).
    """
    actor_dir = out_dir / ".actor"
    src_dir = out_dir / "src"
    actor_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, Path] = {}

    # actor.json (v1 spec)
    actor_json = actor_dir / "actor.json"
    actor_json.write_text(json.dumps(spec.to_actor_json(), indent=4) + "\n")
    files["actor.json"] = actor_json

    # INPUT_SCHEMA.json (platform auto-detects this path).
    # Must be byte-equivalent to the embedded actor.json input - both come
    # from _input_schema() so winner-pattern fields stay in lockstep.
    input_schema = spec._input_schema()
    if not input_schema.get("required"):
        input_schema.pop("required", None)
    isj = actor_dir / "INPUT_SCHEMA.json"
    isj.write_text(json.dumps(input_schema, indent=4) + "\n")
    files["INPUT_SCHEMA.json"] = isj

    # Dockerfile
    dockerfile = actor_dir / "Dockerfile"
    dockerfile.write_text(DOCKERFILE_TEMPLATE.format(title=spec.title))
    files["Dockerfile"] = dockerfile

    # README.md (store-facing)
    readme = actor_dir / "README.md"
    readme.write_text(_render_readme(spec))
    files["README.md"] = readme

    # src/main.py wired to the shared PPE runtime
    main_py = src_dir / "main.py"
    main_py.write_text(
        MAIN_TEMPLATE.format(
            title=spec.title,
            primary_event=spec.primary_event().name,
            output_format=_default_output_format(spec),
            processor_line=(
                f'processor_name="{spec.processor}",' if spec.processor else "processor_name=None,"
            ),
        )
    )
    files["src/main.py"] = main_py

    # icon.svg (Console Display-information logo, ready to upload)
    from actor_factory.icons import render_icon

    icon = actor_dir / "icon.svg"
    icon.write_text(render_icon(spec))
    files["icon.svg"] = icon

    # Curated badge PNG (canonical store card icon, badge-256): ship the
    # same badge the MCP catalog exposes so ``apify push`` carries it. Copied
    # (not text-tracked) so the binary stays out of the GeneratedActor.files
    # text map that read_text() walks. All 94 presets have a matching badge.
    from actor_factory.spec import ICON_DIR_256

    badge_src = Path(__file__).resolve().parents[1] / ICON_DIR_256 / f"{spec.name}.png"
    if not badge_src.is_file():
        raise FileNotFoundError(f"{spec.name}: curated badge icon missing: {badge_src}")
    icon_png = actor_dir / "icon.png"
    icon_png.write_bytes(badge_src.read_bytes())

    # per-actor CHANGELOG (docs: displayed in Console Information tab)
    changelog = actor_dir / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## {spec.version}\n\n- Initial release via Actor Factory.\n"
    )
    files["CHANGELOG.md"] = changelog

    # dataset schema (storages.dataset) - Apify dataset-schema contract:
    # actorSpecification 1 + JSON-Schema fields + Console Output-tab views.
    dataset_schema = actor_dir / "dataset_schema.json"
    dataset_schema.write_text(json.dumps(spec._dataset_schema(), indent=4) + "\n")
    files["dataset_schema.json"] = dataset_schema

    # output schema (Store publication REQUIRES it) - link definitions for
    # the Console Output tab and the run API "output" property.
    output_schema = actor_dir / "output_schema.json"
    output_schema.write_text(json.dumps(spec._output_schema(), indent=4) + "\n")
    files["output_schema.json"] = output_schema

    return GeneratedActor(out_dir=out_dir, files=files)


def validate_generated(files: dict[str, Path]) -> list[str]:
    """Post-generation sanity checks. Returns a list of problems."""
    problems: list[str] = []
    spec = json.loads(files["actor.json"].read_text())
    if spec.get("actorSpecification") != 1:
        problems.append("actorSpecification must be 1")
    if not re.match(r"^\d+\.\d+$", str(spec.get("version", ""))):
        problems.append(f"version '{spec.get('version')}' must be [N].[N]")
    if spec.get("dockerfile") != "./Dockerfile":
        problems.append("dockerfile must be './Dockerfile'")
    if not files["Dockerfile"].exists():
        problems.append("Dockerfile missing")
    ischema = json.loads(files["INPUT_SCHEMA.json"].read_text())
    if ischema.get("schemaVersion") != 1:
        problems.append("input schemaVersion must be 1")
    if "urls" not in ischema.get("properties", {}):
        problems.append("input schema missing 'urls'")
    main_src = files["src/main.py"].read_text()
    if "PPEScraperRunner" not in main_src:
        problems.append("main.py not wired to PPEScraperRunner")
    icon = files.get("icon.svg")
    if icon is None or not icon.exists():
        problems.append("icon.svg missing (Console logo upload requires it)")
    elif 'viewBox="0 0 256 256"' not in icon.read_text():
        problems.append("icon.svg missing 256x256 viewBox")
    return problems


def to_jsonable(obj: Any) -> Any:
    """JSON-safety helper for specs (used by tests and CLI)."""
    if hasattr(obj, "to_actor_json"):
        return obj.to_actor_json()
    raise TypeError(type(obj).__name__)
