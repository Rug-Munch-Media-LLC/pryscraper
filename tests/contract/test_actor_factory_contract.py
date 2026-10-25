"""Contract tests for the actor factory surface (pry.commerce.actor_marketplace).

Scope: the input/output *shape* of the actor object model and its preset catalog.
These are the paths every actor create/run request goes through, so they are the
ones worth pinning — not blanket coverage. Run explicitly (default addopts ignores
tests/contract):

    pytest tests/contract/test_actor_factory_contract.py -o addopts=""
"""
from __future__ import annotations

import pytest

from pry.commerce.actor_marketplace import Actor, ActorVisibility, preset_specs

REQUIRED_ACTOR_FIELDS = {
    "actor_id",
    "name",
    "description",
    "template_id",
    "code",
    "price_per_run",
    "visibility",
    "schedule_cron",
    "tags",
    "author",
    "created_at",
    "run_count",
    "revenue_usd",
}


def test_actor_to_dict_exposes_request_response_schema():
    """A created actor must serialize with every field a run request can set."""
    actor = Actor(actor_id="a1", name="n", description="d")
    payload = actor.to_dict()

    missing = REQUIRED_ACTOR_FIELDS - set(payload)
    assert not missing, f"actor wire schema lost fields: {sorted(missing)}"
    assert payload["actor_id"] == "a1"
    assert payload["price_per_run"] == 0.0
    assert payload["run_count"] == 0
    assert payload["tags"] == []
    assert isinstance(payload["created_at"], str) and payload["created_at"]


def test_actor_visibility_contract_values():
    """Visibility values are part of the public API (create-request input)."""
    assert {v.value for v in ActorVisibility} == {"private", "public", "unlist"}
    assert Actor(actor_id="a", name="n", description="d").visibility is ActorVisibility.PRIVATE


def test_preset_catalog_shape_contract():
    """`preset_specs()` is the actor-factory entry point; it must be a mapping."""
    specs = preset_specs()
    assert isinstance(specs, dict)
    if not specs:
        pytest.skip("actor_factory presets not installed in this environment")
    for preset_id, spec in specs.items():
        assert isinstance(preset_id, str) and preset_id
        assert spec is not None
