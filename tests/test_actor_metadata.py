# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for Store publication metadata (actor_factory.metadata).

Contract coverage for the post-deploy sweep: every preset must map to a
platform-valid store category, PPE payloads must mirror the
PayPerEventActorPricingInfo schema, and the publication PUT must carry
isPublic + categories + pricingInfos together (the platform rejects
isPublic without categories - the 2026-08-26 silent-sweep root cause).
Network is always mocked; no API calls in tests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from actor_factory import metadata
from actor_factory.metadata import (
    APIFY_VALID_CATEGORIES,
    PRESET_CATEGORY_MAP,
    build_pricing_infos,
    build_publication_payload,
    category_for,
    publish_metadata,
)
from actor_factory.presets import ALL_PRESETS

# ── category mapping ─────────────────────────────────────────────────────────


class TestCategoryMap:
    def test_map_is_total_over_presets(self) -> None:
        missing = sorted(set(ALL_PRESETS) - set(PRESET_CATEGORY_MAP))
        extra = sorted(set(PRESET_CATEGORY_MAP) - set(ALL_PRESETS))
        assert not missing, f"presets without category: {missing}"
        assert not extra, f"stale map entries (no such preset): {extra}"

    def test_every_category_is_platform_valid(self) -> None:
        bad = {n: c for n, c in PRESET_CATEGORY_MAP.items() if c not in APIFY_VALID_CATEGORIES}
        assert not bad, f"categories the platform would reject: {bad}"

    def test_category_for_unknown_preset_raises(self) -> None:
        with pytest.raises(KeyError):
            category_for("pry-does-not-exist")

    def test_no_category_collides_across_namespaces(self) -> None:
        # Sanity: values are plain uppercase enums, never lists/None.
        assert all(isinstance(c, str) and c.isupper() for c in PRESET_CATEGORY_MAP.values())


# ── pricing payload ──────────────────────────────────────────────────────────


class TestPricingInfos:
    def test_single_event_shape(self) -> None:
        spec = ALL_PRESETS["pry-universal-scraper"]
        infos = build_pricing_infos(spec)
        assert infos["pricingModel"] == "PAY_PER_EVENT"
        events = infos["pricingPerEvent"]["actorChargeEvents"]
        assert set(events) == {"page-scraped"}
        ev = events["page-scraped"]
        assert ev["eventPriceUsd"] == 0.003
        assert ev["eventTitle"] == "Page scraped"
        assert ev["eventDescription"]
        assert ev["isPrimaryEvent"] is True

    def test_multi_event_marks_only_first_primary(self) -> None:
        spec = ALL_PRESETS["pry-change-monitor"]  # page-checked + change-detected
        events = build_pricing_infos(spec)["pricingPerEvent"]["actorChargeEvents"]
        primaries = [n for n, e in events.items() if e.get("isPrimaryEvent")]
        assert len(events) == 2
        assert primaries == ["page-checked"]

    def test_prices_match_spec_exactly(self) -> None:
        for name in ("pry-serp-scraper", "pry-token-safety-scanner", "pry-rss-feed-monitor"):
            spec = ALL_PRESETS[name]
            events = build_pricing_infos(spec)["pricingPerEvent"]["actorChargeEvents"]
            expected = {e.name: e.price_usd for e in spec.pricing_events}
            assert {n: e["eventPriceUsd"] for n, e in events.items()} == expected

    def test_preset_without_events_raises(self) -> None:
        from actor_factory.spec import ActorSpec

        bare = ActorSpec(name="pry-x", title="X", description="d")
        with pytest.raises(ValueError, match="no pricing events"):
            build_pricing_infos(bare)


# ── publication payload ──────────────────────────────────────────────────────


class TestPublicationPayload:
    def test_payload_is_complete_for_every_preset(self) -> None:
        for name, spec in ALL_PRESETS.items():
            payload = build_publication_payload(spec)
            assert payload["isPublic"] is True, name
            assert payload["title"] == spec.title, name
            assert payload["description"] == spec.description, name
            cats = payload["categories"]
            assert isinstance(cats, list), name
            assert len(cats) == 1, name
            assert cats[0] in APIFY_VALID_CATEGORIES, name
            assert payload["pricingInfos"][0]["pricingModel"] == "PAY_PER_EVENT", name

    def test_payload_is_json_serializable(self) -> None:
        # The PUT body crosses curl/subprocess boundaries; must round-trip.
        payload = build_publication_payload(ALL_PRESETS["pry-wayback-diff"])
        assert json.loads(json.dumps(payload)) == payload


# ── publish_metadata ─────────────────────────────────────────────────────────


class TestPublishMetadata:
    def _patch_request(
        self,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
        body: dict[str, Any] | str,
    ) -> list[tuple[str, str, dict | None]]:
        calls: list[tuple[str, str, dict | None]] = []

        def fake(path: str, method: str, token: str, payload: dict | None = None):
            calls.append((path, method, payload))
            return status, body

        monkeypatch.setattr(metadata, "_request", fake)
        return calls

    def test_success_reports_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_request(
            monkeypatch,
            200,
            {"data": {"isPublic": True, "categories": ["AUTOMATION"]}},
        )
        ok, detail = publish_metadata(ALL_PRESETS["pry-universal-scraper"], "tok")
        assert ok is True
        assert "public=True" in detail

    def test_put_targets_org_scoped_actor_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._patch_request(monkeypatch, 200, {"data": {}})
        publish_metadata(ALL_PRESETS["pry-universal-scraper"], "tok", org="rugmunchmedia")
        path, method, payload = calls[0]
        assert path == "/acts/rugmunchmedia~universal-scraper"
        assert method == "PUT"
        assert payload is not None
        assert payload["isPublic"] is True

    def test_account_blocker_reported_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_request(
            monkeypatch,
            403,
            json.dumps({"error": {"type": "store-terms-not-accepted"}}),
        )
        ok, detail = publish_metadata(ALL_PRESETS["pry-universal-scraper"], "tok")
        assert ok is False
        assert "store-terms-not-accepted" in detail

    def test_schema_error_reported_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_request(
            monkeypatch,
            400,
            json.dumps({"error": {"type": "schema-validation"}}),
        )
        ok, detail = publish_metadata(ALL_PRESETS["pry-universal-scraper"], "tok")
        assert ok is False
        assert "HTTP 400" in detail

    def test_actor_name_strips_pry_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._patch_request(monkeypatch, 200, {"data": {}})
        publish_metadata(ALL_PRESETS["pry-token-unlock-monitor"], "tok")
        assert calls[0][0] == "/acts/rugmunchmedia~token-unlock-monitor"
