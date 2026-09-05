"""Pry - Apify Actor Factory: flagship actor presets (thin loader).

The preset catalog is data-driven: every actor definition lives as plain
JSON under ``actor_factory/presets/*.json`` (grouped by domain). This module
is a thin loader that reads those files, reconstructs the typed
:class:`~actor_factory.spec.ActorSpec` objects, and exposes the public API:

- ``ALL_PRESETS`` — ``{actor_name: ActorSpec}`` (single source of truth)
- ``SCRAPER_ACTOR`` / ``MONITOR_ACTOR`` — convenience aliases kept for
  backward compatibility with existing imports.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from actor_factory.spec import ActorSpec, InputField, PricingEvent

_PRESETS_DIR = Path(__file__).resolve().parent / "presets"


def _field_from_dict(data: dict[str, Any]) -> InputField:
    """Reconstruct an InputField from its JSON representation."""
    return InputField(
        name=data["name"],
        title=data["title"],
        type=data.get("type", "string"),
        description=data.get("description", ""),
        editor=data.get("editor"),
        prefill=data.get("prefill"),
        default=data.get("default"),
        required=data.get("required", False),
        enum=data.get("enum"),
        enum_titles=data.get("enum_titles"),
        minimum=data.get("minimum"),
        maximum=data.get("maximum"),
        section_caption=data.get("section_caption"),
        item_type=data.get("item_type"),
    )


def _event_from_dict(data: dict[str, Any]) -> PricingEvent:
    """Reconstruct a PricingEvent from its JSON representation."""
    return PricingEvent(
        name=data["name"],
        title=data["title"],
        description=data.get("description", ""),
        price_usd=data["price_usd"],
    )


def _spec_from_dict(data: dict[str, Any]) -> ActorSpec:
    """Reconstruct an ActorSpec from its JSON representation."""
    return ActorSpec(
        name=data["name"],
        title=data["title"],
        description=data["description"],
        version=data.get("version", "1.0"),
        category=data.get("category", "SCRAPER"),
        inputs=tuple(_field_from_dict(f) for f in data.get("inputs", [])),
        pricing_events=tuple(_event_from_dict(e) for e in data.get("pricing_events", [])),
        min_memory_mbytes=data.get("min_memory_mbytes", 512),
        max_memory_mbytes=data.get("max_memory_mbytes", 4096),
        build_tag=data.get("build_tag", "latest"),
        uses_browser=data.get("uses_browser", True),
        processor=data.get("processor"),
    )


def _load_all_presets() -> dict[str, ActorSpec]:
    """Load every preset from the JSON catalog into ``{name: ActorSpec}``."""
    presets: dict[str, ActorSpec] = {}
    for json_file in sorted(_PRESETS_DIR.glob("*.json")):
        with json_file.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        for entry in payload:
            spec = _spec_from_dict(entry)
            if spec.name in presets:
                raise ValueError(f"duplicate preset name '{spec.name}' across catalog files")
            presets[spec.name] = spec
    return presets


ALL_PRESETS: dict[str, ActorSpec] = _load_all_presets()

# Backward-compatible convenience aliases (kept for existing imports).
SCRAPER_ACTOR: ActorSpec = ALL_PRESETS["pry-universal-scraper"]
MONITOR_ACTOR: ActorSpec = ALL_PRESETS["pry-change-monitor"]

__all__ = [
    "ALL_PRESETS",
    "MONITOR_ACTOR",
    "SCRAPER_ACTOR",
]
