"""Pry — Apify Actor Factory: specification types.

Encodes Apify's actor.json v1 specification (docs.apify.com/actors/
development/actor-definition/actor-json) and the pay-per-event monetization
model (docs.apify.com/actors/publishing/monetize/pay-per-event) as typed
Python objects. The generator turns these into deployable `.actor` packages.

Spec rules enforced here (verified against Apify docs 2026-08-23):
- ``actorSpecification`` is always 1.
- ``version`` MUST be ``[Number].[Number]`` (e.g. "1.0") - NOT semver.
- ``dockerfile`` is lowercase; defaults to ./Dockerfile search path.
- Input schemas are JSON-Schema objects with ``schemaVersion: 1`` and
  platform ``editor`` hints per field.
- PPE pricing: custom events are charged via Actor.charge(); the synthetic
  events apify-actor-start / apify-default-dataset-item are auto-charged by
  the platform and must NEVER be charged manually.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

VERSION_RE = re.compile(r"^\d+\.\d+$")

# Real Apify platform editor vocabulary (upload validation fails on
# anything else; numeric fields accept ONLY "number"/"hidden").
VALID_EDITORS = {
    "string",
    "textfield",
    "textarea",
    "select",
    "boolean",
    "number",
    "json",
    "stringList",
    "requestListSources",
    "keyValue",
    "dateInterval",
    "hidden",
}

SYNTHETIC_EVENTS = {"apify-actor-start", "apify-default-dataset-item"}


EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_version(version: str) -> str:
    if not VERSION_RE.match(version):
        raise ValueError(
            f"version '{version}' violates Apify spec: must be [Number].[Number], e.g. '1.0'"
        )
    return version


@dataclass(frozen=True)
class InputField:
    """One property of an actor's input schema."""

    name: str
    title: str
    type: str = "string"
    description: str = ""
    editor: str | None = None
    prefill: Any = None
    default: Any = None
    required: bool = False
    enum: list[str] | None = None
    enum_titles: list[str] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    section_caption: str | None = None
    item_type: str | None = None  # for arrays of strings

    def __post_init__(self) -> None:
        # Numeric fields MUST carry editor="number" (Apify platform rule)
        if self.editor is None and self.type in ("integer", "float"):
            object.__setattr__(self, "editor", "number")  # frozen dataclass

    def _default_editor(self) -> str:
        if self.type == "boolean":
            return "boolean"
        if self.type == "integer":
            return "integer"
        if self.type == "float":
            return "float"
        if self.type == "object":
            return "json"
        if self.type == "array":
            return "requestListSources" if self.name in ("urls", "requests", "start_urls") else "stringList"
        if self.enum:
            return "select"
        return "textfield"

    def _default_editor(self) -> str:
        if self.type in ("integer", "float"):
            return "number"
        if self.type == "boolean":
            return "boolean"
        if self.type == "object":
            return "json"
        if self.type == "array":
            return ("requestListSources"
                    if self.name in ("urls", "requests", "start_urls")
                    else "stringList")
        if self.enum:
            return "select"
        return "textfield"

    def to_schema(self) -> dict[str, Any]:
        if self.editor is not None and self.editor not in VALID_EDITORS:
            raise ValueError(f"field '{self.name}': editor '{self.editor}' not in Apify editor set")
        prop: dict[str, Any] = {
            "title": self.title,
            "type": self.type,
            "description": self.description,
        }
        if self.section_caption:
            prop["sectionCaption"] = self.section_caption
        # Apify platform REQUIRES an editor on every property — upload
        # fails validation without one. Default by type when unset.
        prop["editor"] = self.editor or self._default_editor()
        if self.default is not None:
            prop["default"] = self.default
        if self.prefill is not None:
            prop["prefill"] = self.prefill
        if self.enum is not None:
            prop["enum"] = self.enum
        if self.enum_titles is not None:
            prop["enumTitles"] = self.enum_titles
        if self.minimum is not None:
            prop["minimum"] = self.minimum
        if self.maximum is not None:
            prop["maximum"] = self.maximum
        if self.type == "array" and self.item_type:
            prop["items"] = {"type": self.item_type}
        # Store sample runs are generated from `example` values (Apify docs:
        # input-schema specification). Fall back to prefill/default so every
        # published actor ships a working sample without per-spec boilerplate.
        example = self.prefill if self.prefill is not None else self.default
        if example is not None:
            prop["example"] = example
        return prop


@dataclass(frozen=True)
class PricingEvent:
    """A custom pay-per-event chargeable action.

    Names must be lowercase-kebab and NOT collide with Apify's synthetic
    events (those are billed automatically by the platform).
    """

    name: str
    title: str
    description: str
    price_usd: float

    def __post_init__(self) -> None:
        if not EVENT_NAME_RE.match(self.name):
            raise ValueError(f"event '{self.name}': use lowercase kebab-case (a-z, 0-9, dashes)")
        if self.name in SYNTHETIC_EVENTS:
            raise ValueError(
                f"event '{self.name}' is a platform synthetic event - it is "
                "auto-charged and must never be defined or charged manually"
            )
        if self.price_usd <= 0:
            raise ValueError(f"event '{self.name}': price must be positive")


# Winner-pattern fields appended to every generated actor (docs patterns:
# proxy passthrough + visible cost cap). See MARKET-ANALYSIS.md.
WINNER_MAX_ITEMS_FIELD = InputField(
    name="max_items",
    title="Max items (cost cap)",
    type="integer",
    description=(
        "Hard cap on processed items for this run - keeps trial costs "
        "predictable. Billing stops when the cap or your spending limit "
        "is reached."
    ),
    minimum=1,
    default=25,
    section_caption="Advanced",
)

WINNER_PROXY_FIELD = InputField(
    name="proxy_configuration",
    title="Proxy configuration",
    type="object",
    description=(
        "Apify proxy settings passed through to Pry's premium-proxy tier. "
        "Leave default to use the platform proxy automatically."
    ),
    editor="hidden",
    prefill={"useApifyProxy": True},
    section_caption="Advanced",
)


@dataclass(frozen=True)
class ActorSpec:
    """Complete specification for a generated Apify actor."""

    name: str
    title: str
    description: str
    version: str = "1.0"
    category: str = "SCRAPER"
    inputs: tuple[InputField, ...] = ()
    pricing_events: tuple[PricingEvent, ...] = ()
    min_memory_mbytes: int = 512
    max_memory_mbytes: int = 4096
    build_tag: str = "latest"
    uses_browser: bool = True  # Chromium in image => higher memory floor
    processor: str | None = None  # actor_factory.processors registry key

    def __post_init__(self) -> None:
        _validate_version(self.version)
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", self.name):
            raise ValueError(f"name '{self.name}': lowercase alphanumerics and dashes only")
        names = [f.name for f in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("duplicate input field names")
        event_names = [e.name for e in self.pricing_events]
        if len(event_names) != len(set(event_names)):
            raise ValueError("duplicate pricing event names")
        if self.min_memory_mbytes > self.max_memory_mbytes:
            raise ValueError("minMemoryMbytes exceeds maxMemoryMbytes")
        if self.uses_browser and self.min_memory_mbytes < 512:
            # Docs: browser-based scraping needs more memory; keep users from
            # under-provisioning into OOM.
            raise ValueError("browser actors need minMemoryMbytes >= 512")
        from actor_factory.processors import PROCESSORS

        known = set(PROCESSORS)
        if self.processor is not None and self.processor not in known:
            raise ValueError(
                f"processor '{self.processor}' not in factory registry {sorted(known)}"
            )

    def effective_inputs(self) -> tuple[InputField, ...]:
        """Inputs plus the standard winner-pattern fields every actor exposes.

        Reverse-engineered from top PPE actors (see MARKET-ANALYSIS.md):
        proxy passthrough and an explicit cost-cap input. Skipped when the
        preset already declares them.
        """
        declared = {f.name for f in self.inputs}
        extra = [f for f in (WINNER_MAX_ITEMS_FIELD, WINNER_PROXY_FIELD) if f.name not in declared]
        return (*self.inputs, *extra)

    def primary_event(self) -> PricingEvent:
        """The event best representing core value (first defined)."""
        if not self.pricing_events:
            raise ValueError(f"actor '{self.name}' has no pricing events")
        return self.pricing_events[0]

    def to_actor_json(self) -> dict[str, Any]:
        """Render the spec-compliant actor.json object."""
        return {
            "actorSpecification": 1,
            "name": self.name.removeprefix("pry-"),
            # Store title = what it DOES (SEO), no brand prefix
            "title": self.title.removeprefix("Pry ").strip(),
            "description": self.description,
            "version": self.version,
            "buildTag": self.build_tag,
            "meta": {"templateId": "pry-actor-factory"},
            "dockerfile": "./Dockerfile",
            "minMemoryMbytes": self.min_memory_mbytes,
            "maxMemoryMbytes": self.max_memory_mbytes,
            "input": self._input_schema(),
            "output": "./output_schema.json",
            "storages": {"dataset": "./dataset_schema.json"},
        }

    def _input_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for f in self.effective_inputs():
            prop = f.to_schema()
            properties[f.name] = prop
            if f.required:
                required.append(f.name)
        schema = {
            "title": f"Input schema for {self.title}",
            "description": self.description,
            "type": "object",
            "schemaVersion": 1,
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def _output_schema(self) -> dict[str, Any]:
        """Apify output schema FILE content (.actor/output_schema.json).

        Contract per Apify docs (actors/development/actor-definition/output-schema)
        and the official apify/actor-schemas-example reference: top level carries
        actorOutputSchemaVersion + title; properties entries are output LINK
        definitions ({type, title, description, template}). Templates interpolate
        run context variables like {{links.apiDefaultDatasetUrl}}. An output
        schema is REQUIRED for Apify Store publication. Referenced from
        actor.json as "output": "./output_schema.json" (path form - mirrors
        the platform-validated reference example).
        """
        return {
            "actorOutputSchemaVersion": 1,
            "title": f"Output of {self.title}",
            "properties": {
                "results": {
                    "type": "string",
                    "title": "Results",
                    "description": (
                        "One item per processed URL: url, status, content, "
                        "method tier, scraped_at, metadata."
                    ),
                    "template": "{{links.apiDefaultDatasetUrl}}/items",
                },
            },
        }

    def _dataset_schema(self) -> dict[str, Any]:
        """Apify dataset schema for the default dataset (storages.dataset).

        Contract per Apify docs (storage/dataset-schema): actorSpecification 1,
        optional JSON-Schema ``fields`` describing one dataset item, and
        required ``views`` controlling Console Output-tab rendering.
        """
        item_properties: dict[str, Any] = {
            "url": {"type": "string", "title": "URL"},
            "status": {"type": "string", "title": "Status"},
            "content": {"type": "string", "title": "Content"},
            "method": {"type": "string", "title": "Method"},
            "error": {"type": "string", "title": "Error"},
            "scraped_at": {"type": "string", "title": "Scraped at"},
            "metadata": {"type": "object", "title": "Metadata"},
        }
        return {
            "actorSpecification": 1,
            "fields": {
                "type": "object",
                "properties": item_properties,
            },
            "views": {
                "overview": {
                    "title": "Overview",
                    "transformation": {
                        "fields": ["url", "status", "method", "scraped_at"],
                    },
                    "display": {"component": "table"},
                },
            },
        }
