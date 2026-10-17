# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Cache isolation: option/schema/tenant separation and share eviction."""

from __future__ import annotations

from pry.api.routers.core import share as share_mod
from pry.core.cache import ResponseCache

URL = "https://example.com/page"
PAGE = {"success": True, "data": {"markdown": "# hi", "metadata": {"url": URL}}}


def _extracted(marker: str) -> dict:
    return {
        "success": True,
        "data": {
            "markdown": "# hi",
            "metadata": {"url": URL},
            "json": {"entity": marker},
        },
    }


def test_different_json_schema_does_not_share() -> None:
    cache = ResponseCache(capacity=10)
    cache.set(URL, PAGE, {"jsonSchema": {"type": "object", "title": "A"}})
    assert cache.get(URL, {"jsonSchema": {"type": "object", "title": "B"}}) is None
    assert cache.get(URL, {"jsonSchema": {"type": "object", "title": "A"}}) is not None


def test_different_formats_does_not_share() -> None:
    cache = ResponseCache(capacity=10)
    cache.set(URL, PAGE, {"formats": ["markdown"]})
    assert cache.get(URL, {"formats": ["text"]}) is None
    assert cache.get(URL, {"formats": ["markdown"]}) is not None


def test_extraction_payload_requires_schema_in_key() -> None:
    cache = ResponseCache(capacity=10)
    # No schema in the key: the extracted JSON must not be cached at all.
    cache.set(URL, _extracted("alpha"), {"formats": ["json"]})
    assert cache.get(URL, {"formats": ["json"]}) is None
    assert cache.stats()["size"] == 0
    # Schema present: cached, and a different schema still misses.
    schema_a = {"jsonSchema": {"properties": {"a": {"type": "string"}}}}
    schema_b = {"jsonSchema": {"properties": {"b": {"type": "string"}}}}
    cache.set(URL, _extracted("alpha"), schema_a)
    assert cache.get(URL, schema_b) is None
    hit = cache.get(URL, schema_a)
    assert hit is not None
    assert hit["data"]["json"]["entity"] == "alpha"


def test_different_tenants_do_not_share() -> None:
    cache = ResponseCache(capacity=10)
    cache.set(URL, PAGE, {"tenant": "alpha"})
    assert cache.get(URL, {"tenant": "beta"}) is None
    assert cache.get(URL, {"tenant": "alpha"}) is not None


def test_different_api_keys_do_not_share() -> None:
    cache = ResponseCache(capacity=10)
    cache.set(URL, PAGE, {"api_key": "key-one"})
    assert cache.get(URL, {"api_key": "key-two"}) is None
    assert cache.get(URL, {"api_key": "key-one"}) is not None


def test_share_cap_evicts_oldest(monkeypatch) -> None:
    monkeypatch.setattr(share_mod, "_SHARES_MAX", 2)
    share_mod._shares.clear()
    for sid in ("s1", "s2", "s3"):
        share_mod._store_share(sid, {"url": URL, "title": sid, "content": "", "method": "x"})
    assert share_mod._get_share("s1") is None
    assert share_mod._get_share("s2") is not None
    assert share_mod._get_share("s3") is not None
    assert len(share_mod._shares) == 2
    share_mod._shares.clear()


def test_share_expires_after_ttl(monkeypatch) -> None:
    monkeypatch.setattr(share_mod, "_SHARE_TTL_SECONDS", 0)
    share_mod._shares.clear()
    share_mod._store_share("old", {"url": URL, "title": "t", "content": "", "method": "x"})
    assert share_mod._get_share("old") is None
    assert len(share_mod._shares) == 0
