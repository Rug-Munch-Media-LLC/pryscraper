"""Tests for the MCP tool argument validation seam (audit item #24).

Covers pry_mcp.validation: TOOL_REQUIREMENTS table, validate_tool_args,
dispatch_safely, and the combined_tool_executor wiring.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

import pytest

from pry_mcp.validation import TOOL_REQUIREMENTS, ToolArgError, dispatch_safely, validate_tool_args


class TestToolArgErrorMessages:
    def test_args_not_a_dict_names_tool(self) -> None:
        with pytest.raises(ToolArgError) as exc_info:
            validate_tool_args("pry_scrape", "not-a-dict")
        assert "pry_scrape" in str(exc_info.value)

    def test_required_field_missing_names_field(self) -> None:
        with pytest.raises(ToolArgError) as exc_info:
            validate_tool_args("pry_scrape", {"bypass_cloudflare": True})
        assert "url" in str(exc_info.value)

    def test_wrong_type_on_required_field_rejected(self) -> None:
        with pytest.raises(ToolArgError) as exc_info:
            validate_tool_args("pry_scrape", {"url": 12345})
        assert "url" in str(exc_info.value)
        assert "str" in str(exc_info.value)

    def test_wrong_type_on_second_required_field(self) -> None:
        with pytest.raises(ToolArgError):
            validate_tool_args("pry_monitor", {"name": "watch", "url": ["not", "a", "string"]})

    def test_bool_is_not_accepted_for_patched_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # bool subclasses int; must not silently pass an int check.
        monkeypatch.setitem(TOOL_REQUIREMENTS, "pry_test_int", (("count", int),))
        with pytest.raises(ToolArgError):
            validate_tool_args("pry_test_int", {"count": True})


class TestCoercion:
    def test_str_coerced_to_int_when_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No top-20 tool has a required int field; patch the table to exercise
        # the int coercion path directly.
        monkeypatch.setitem(TOOL_REQUIREMENTS, "pry_test_int", (("count", int),))
        result = validate_tool_args("pry_test_int", {"count": "5"})
        assert result["count"] == 5
        assert isinstance(result["count"], int)

    def test_str_not_coercible_to_int_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(TOOL_REQUIREMENTS, "pry_test_int", (("count", int),))
        with pytest.raises(ToolArgError):
            validate_tool_args("pry_test_int", {"count": "abc"})


class TestPassthrough:
    def test_unknown_tool_passes_through_unvalidated(self) -> None:
        args: dict[str, Any] = {"whatever": object(), "url": 123}
        result = validate_tool_args("pry_not_in_table", args)
        assert result == args

    def test_unknown_tool_non_dict_becomes_empty(self) -> None:
        assert validate_tool_args("pry_not_in_table", "junk") == {}

    def test_extra_fields_pass_through(self) -> None:
        result = validate_tool_args("pry_scrape", {"url": "https://x.com", "extra": {"a": 1}})
        expected = {"a": 1}
        assert result["extra"] == expected

    def test_no_required_fields_tool_accepts_empty(self) -> None:
        assert validate_tool_args("pry_x402_pricing", {}) == {}


class TestTable:
    def test_top_20_tools_covered(self) -> None:
        assert len(TOOL_REQUIREMENTS) == 20

    def test_high_risk_tools_present(self) -> None:
        for name in (
            "pry_scrape",
            "pry_crawl",
            "pry_monitor",
            "pry_actor_run",
            "pry_buy_pack",
            "pry_balance",
        ):
            assert name in TOOL_REQUIREMENTS

    def test_table_matches_registry_required_fields(self) -> None:
        """Every table entry must agree with the tool's own inputSchema."""
        from pry_mcp.tools import PRY_TOOLS

        schemas = {t["name"]: t.get("inputSchema", {}) for t in PRY_TOOLS}
        for name, requirements in TOOL_REQUIREMENTS.items():
            schema = schemas[name]
            required = set(schema.get("required", []))
            table_fields = {field for field, _ in requirements}
            assert table_fields == required, f"{name}: table {table_fields} != schema {required}"
            for field, expected in requirements:
                js_type = schema["properties"][field]["type"]
                assert _JS_TO_PY[js_type] is expected


_JS_TO_PY = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class TestDispatchSafely:
    async def test_catches_internal_raise(self) -> None:
        async def boom(name: str, args: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

        result = await dispatch_safely(boom, "pry_scrape", {"url": "https://x.com"})
        assert result["error"]["code"] == "tool_failed"
        assert "boom" in result["error"]["message"]

    async def test_invalid_args_structured_error(self) -> None:
        async def fn(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        result = await dispatch_safely(fn, "pry_scrape", {"nope": 1})
        assert result["error"]["code"] == "invalid_args"
        assert "url" in result["error"]["message"]

    async def test_success_returns_result(self) -> None:
        async def fn(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "args": args}

        result = await dispatch_safely(fn, "pry_scrape", {"url": "https://x.com"})
        expected = {"ok": True, "args": {"url": "https://x.com"}}
        assert result == expected

    async def test_sync_fn_supported(self) -> None:
        def fn(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"sync": True}

        expected = {"sync": True}
        assert await dispatch_safely(fn, "pry_scrape", {"url": "https://x.com"}) == expected

    async def test_base_exception_not_swallowed(self) -> None:
        async def fn(name: str, args: dict[str, Any]) -> dict[str, Any]:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            await dispatch_safely(fn, "pry_scrape", {"url": "https://x.com"})


class TestExecutorWiring:
    async def test_combined_executor_returns_invalid_args_error(self) -> None:
        from pry_mcp.fallback_server import combined_tool_executor

        result = await combined_tool_executor("pry_scrape", {"url": 42})
        assert result["error"]["code"] == "invalid_args"
        assert result["isError"] is True

    async def test_combined_executor_not_handled_still_propagates(self) -> None:
        from pry_mcp.fallback_server import _ToolNotHandled, combined_tool_executor

        with pytest.raises(_ToolNotHandled):
            await combined_tool_executor("pry_definitely_not_a_tool", {})
