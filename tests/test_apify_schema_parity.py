# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Schema/Pydantic parity for the flagship Apify actor.

The Apify actor ``.actor/INPUT_SCHEMA.json`` (and the ``input`` block embedded
in ``.actor/actor.json``) is the contract Apify validates user input against
BEFORE the actor runs. The runtime contract is the Pydantic model
``ApifyActorInput`` in ``src/pry/actors/apify_actor.py``. If the two drift, the
Console offers a field the runner rejects - or, worse, validates input the
runner silently ignores (this is how the orphan lowercase ``input_schema.json``
once diverged from the canonical schema).

These tests pin both schema surfaces to the Python model field-by-field
(names, enum values, defaults) so the drift cannot recur.

Deliberately STATIC: no network, no actor runtime, no SDK.
"""

from __future__ import annotations

import json
from pathlib import Path

from pry.actors.apify_actor import ApifyActorInput, ApifyProxyConfig

REPO = Path(__file__).resolve().parents[1]
ACTOR_DIR = REPO / ".actor"
STANDALONE = ACTOR_DIR / "INPUT_SCHEMA.json"


def _standalone() -> dict:
    """Parse the auto-detected input schema (fails loudly if absent)."""
    assert STANDALONE.is_file(), "missing .actor/INPUT_SCHEMA.json"
    return json.loads(STANDALONE.read_text())


def _embedded() -> dict:
    """Parse the input schema embedded in actor.json."""
    spec = json.loads((ACTOR_DIR / "actor.json").read_text())
    embedded = spec.get("input")
    assert isinstance(embedded, dict), "actor.json should embed an input schema"
    return embedded


def _model_json_schema() -> dict:
    return ApifyActorInput.model_json_schema()


def _resolve_ref(schema: dict, node: dict) -> dict:
    """Resolve a local ``$ref`` to its definition, else return node as-is."""
    ref = node.get("$ref")
    if not ref:
        return node
    name = ref.rsplit("/", 1)[-1]
    return schema["$defs"][name]


class TestSchemaShape:
    def test_standalone_parses(self) -> None:
        schema = _standalone()
        assert schema.get("type") == "object"
        assert schema.get("schemaVersion") == 1
        assert schema.get("required") == ["urls"]

    def test_embedded_equals_standalone(self) -> None:
        """Apify auto-detects the standalone file; the two must not drift."""
        assert _embedded() == _standalone()


class TestSchemaMatchesPythonModel:
    """Field names + enums + defaults: schema == ApifyActorInput."""

    def test_field_names_match(self) -> None:
        schema = _standalone()
        schema_fields = set(schema["properties"])
        model_fields = set(ApifyActorInput.model_fields)
        assert schema_fields == model_fields, (
            f"schema/model field drift: schema-only={schema_fields - model_fields}, "
            f"model-only={model_fields - schema_fields}"
        )

    def test_required_matches(self) -> None:
        schema = _standalone()
        model_required = {
            name for name, field in ApifyActorInput.model_fields.items() if field.is_required()
        }
        assert set(schema["required"]) == model_required
        assert schema["required"] == ["urls"]

    def test_defaults_match(self) -> None:
        schema = _standalone()
        props = schema["properties"]
        for name, field in ApifyActorInput.model_fields.items():
            if field.is_required():
                continue
            model_default = field.get_default(call_default_factory=True)
            if name == "proxy_config":
                # Nested model default is an object; schema mirrors its shape
                # in the prefill/example blocks (asserted below).
                assert model_default == ApifyProxyConfig()
                continue
            assert props[name]["default"] == model_default, (
                f"default drift on '{name}': schema={props[name].get('default')!r} "
                f"model={model_default!r}"
            )

    def test_output_format_enum_matches(self) -> None:
        model = _model_json_schema()
        prop = model["properties"]["output_format"]
        # Pydantic stores the regex pattern; the schema must expose the same
        # allowed set as an Apify select enum.
        assert prop.get("pattern") == r"^(markdown|html|text|json)$"
        schema_enum = set(_standalone()["properties"]["output_format"]["enum"])
        assert schema_enum == {"markdown", "html", "text", "json"}


class TestProxyConfigParity:
    """The nested proxy object must mirror ApifyProxyConfig exactly."""

    def test_nested_field_names(self) -> None:
        schema = _standalone()
        nested = schema["properties"]["proxy_config"]
        assert nested["type"] == "object"
        assert set(nested["properties"]) == set(ApifyProxyConfig.model_fields)

    def test_nested_defaults(self) -> None:
        model = _model_json_schema()
        nested_model = _resolve_ref(model, model["properties"]["proxy_config"])
        for name, field in ApifyProxyConfig.model_fields.items():
            assert nested_model["properties"][name].get("default") == field.get_default(
                call_default_factory=True
            ), f"nested default drift on 'proxy_config.{name}'"

    def test_prefill_carries_use_apify_proxies_flag(self) -> None:
        """The Console prefill must round-trip through the Pydantic model."""
        nested = _standalone()["properties"]["proxy_config"]
        validated = ApifyActorInput.model_validate(
            {"urls": ["https://example.com"], "proxy_config": nested["prefill"]}
        )
        assert validated.proxy_config == ApifyProxyConfig(
            use_apify_proxies=False, proxy_country="US"
        )

    def test_legacy_proxy_configuration_is_ignored(self) -> None:
        """The removed 'proxy_configuration' name must not populate proxy_config.

        Pydantic ignores unknown fields by default, so the legacy key is
        silently dropped rather than rejected - the model keeps its default
        proxy config. The schema no longer advertises the key either.
        """
        validated = ApifyActorInput.model_validate(
            {"urls": ["https://example.com"], "proxy_configuration": {"useApifyProxy": True}}
        )
        assert validated.proxy_config == ApifyProxyConfig()
        assert "proxy_configuration" not in _standalone()["properties"]
