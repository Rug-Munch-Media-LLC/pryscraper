# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 4b: the 2026-10-23 output-schema alignment stays aligned.

Twenty tools advertised schemas that contradicted their payloads: objects
declared where handlers return arrays (amazon/walmart/tiktok/apps/grants/
flights/resale/tokens/news), and fields declared that no handler ever wrote
(``data.content``, ``availability``, ``reviews_count``, ``market_id``,
``team``, ``sport``, the old sentiment shape). Two commits fixed the
declarations; no test held the fix. These tests do, three ways:

* every affected tool round-trips ``tools/call`` against its emitter payload and
  the emitted ``structuredContent`` satisfies ``outputSchema`` both directions;
* no declared field may be absent from the emitter's own source — the phantom
  check, which is what the hand-fix corrected and what silently returns;
* the two marketplace lookups never report ``success: true`` over an empty
  listing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry_mcp import PRY_TOOLS

from ._contract import validate_payload
from ._emitter_scan import emitted_literals
from ._schema_alignment_tables import (
    ALIGNED_LOCAL,
    ALIGNED_REST,
    EMITTER_MODULES,
    EMPTY_PRODUCT_CASES,
    PAYLOADS,
)
from ._support import _call, _fake_module, _patch_module, _server

TOOLS = {t["name"]: t for t in PRY_TOOLS}


def _contract(name: str, result: dict[str, Any]) -> Any:
    """Assert a result honours its declared outputSchema; return the payload."""
    assert not result.get("isError"), f"{name}: call failed: {result.get('content')}"
    payload = result.get("structuredContent")
    assert payload is not None, f"{name}: no structuredContent despite declaring outputSchema"
    blocks = [b for b in result.get("content", []) if b.get("type") == "text"]
    assert json.loads(blocks[0]["text"]) == payload, f"{name}: text body disagrees"
    validate_payload(payload, TOOLS[name]["outputSchema"])
    return payload


def _data_fields(schema: dict[str, Any], path: bool = False) -> set[str]:
    """Every field name declared anywhere under the ``data`` property."""
    node: dict[str, Any] = (schema.get("properties") or {}).get("data", {}) if not path else schema
    if not isinstance(node, dict):
        return set()
    if isinstance(node.get("items"), dict):
        node = node["items"]
    names = set(node.get("properties") or {})
    for sub in (node.get("properties") or {}).values():
        if isinstance(sub, dict):
            names |= _data_fields(sub, path=True)
    if isinstance(node.get("additionalProperties"), dict):
        names |= _data_fields(node["additionalProperties"], path=True)
    return names


def _local(
    name: str,
    module: str,
    fns: str | tuple[str, ...],
    args: dict[str, Any],
    returns: Any,
) -> dict[str, Any]:
    names = (fns,) if isinstance(fns, str) else fns
    fake = _fake_module(**{fn: AsyncMock(return_value=returns) for fn in names})
    with _patch_module(module, fake):
        return asyncio.run(_call(_server(), name, args))["result"]


def _rest(name: str, args: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    with patch("pry_mcp.fallback_server.get_client", AsyncMock(return_value=client)):
        return asyncio.run(_call(_server(), name, args))["result"]


class TestAlignedPayloads:
    """Emitted payloads still satisfy the corrected declarations."""

    @pytest.mark.parametrize("name", sorted(ALIGNED_LOCAL))
    def test_local_payload_honours_output_schema(self, name: str) -> None:
        module, fn, args = ALIGNED_LOCAL[name]
        payload = _contract(name, _local(name, module, fn, args, PAYLOADS[name]))
        assert payload["success"] is True

    @pytest.mark.parametrize("name", sorted(ALIGNED_REST))
    def test_rest_payload_honours_output_schema(self, name: str) -> None:
        args, expected = ALIGNED_REST[name]
        assert _contract(name, _rest(name, args, expected)) == expected


class TestNoPhantomFields:
    """A declared field the emitter cannot write is the defect this pins down."""

    @pytest.mark.parametrize("name", sorted(EMITTER_MODULES))
    def test_declared_fields_exist_in_emitter_source(self, name: str) -> None:
        emitted = emitted_literals(EMITTER_MODULES[name])
        assert emitted, f"{name}: emitter module not found: {EMITTER_MODULES[name]}"
        phantom = sorted(_data_fields(TOOLS[name]["outputSchema"]) - emitted)
        assert not phantom, (
            f"{name}: outputSchema declares {phantom} but {EMITTER_MODULES[name]} never emits it"
        )


class TestEmptyProductResults:
    """An empty listing is a failure with a reason, never an empty success."""

    @pytest.mark.parametrize("name", sorted(EMPTY_PRODUCT_CASES))
    def test_empty_listing_reports_failure_with_reason(self, name: str) -> None:
        module, fn, args, identifier = EMPTY_PRODUCT_CASES[name]
        result = _local(name, module, fn, args, {})
        assert result["isError"] is True, f"{name}: empty listing reported as success"
        payload = result["structuredContent"]
        assert payload["success"] is False
        assert identifier in payload["error"], f"{name}: reason does not name {identifier}"
        assert payload["code"] == "NOT_FOUND"
        assert json.loads(result["content"][0]["text"]) == payload

    @pytest.mark.parametrize("name", ["pry_amazon_product", "pry_walmart_product"])
    def test_real_listing_still_succeeds(self, name: str) -> None:
        module, fn, args = ALIGNED_LOCAL[name]
        payload = _contract(name, _local(name, module, fn, args, PAYLOADS[name]))
        assert payload["success"] is True
        assert payload["data"]
