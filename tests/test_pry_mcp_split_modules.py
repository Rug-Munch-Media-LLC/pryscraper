# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Focused tests for the modules split out of tool_registry / resources_handler.

The split moved code, not behaviour: these pin the seams that make the split
safe — the tenant-scoped memo, the error envelopes, the dispatch order, and the
resource/prompt/completion facade.
"""

import json

import pytest

from pry_mcp.resources import completion_values, prompt_messages, resource_text
from pry_mcp.resources_handler import ResourceHandler
from pry_mcp.tool_cache import _HOT_TOOL_CACHE_MAX, _hot_tool_cache, hot_cache_get, hot_cache_set
from pry_mcp.tool_errors import HANDLER_ERRORS, ToolNotHandled, handler_failure, structured_error
from pry_mcp.tool_registry import ToolRegistry
from pry_mcp.tool_standard import _DOMAIN_DISPATCHERS, register_standard_executors


@pytest.fixture(autouse=True)
def _clean_memo():
    _hot_tool_cache.clear()
    yield
    _hot_tool_cache.clear()


class TestToolCache:
    def test_identity_argument_keeps_tenants_apart(self) -> None:
        args = {"url": "https://example.com"}
        hot_cache_set("pry_odds", {**args, "api_key": "tenant-a"}, {"n": 1})
        assert hot_cache_get("pry_odds", {**args, "api_key": "tenant-a"}) == {"n": 1}
        assert hot_cache_get("pry_odds", {**args, "api_key": "tenant-b"}) is None

    def test_explicit_identity_wins_over_arguments(self) -> None:
        hot_cache_set("pry_serp", {"q": "x", "api_key": "ignored"}, {"n": 2}, identity="caller")
        assert hot_cache_get("pry_serp", {"q": "x", "api_key": "ignored"}, identity="caller") == {
            "n": 2
        }
        assert hot_cache_get("pry_serp", {"q": "x", "api_key": "ignored"}) is None

    def test_memo_is_bounded(self) -> None:
        for i in range(_HOT_TOOL_CACHE_MAX + 5):
            hot_cache_set("pry_odds", {"i": i}, {"n": i})
        assert len(_hot_tool_cache) == _HOT_TOOL_CACHE_MAX


class TestToolErrors:
    def test_structured_error_carries_both_transports(self) -> None:
        result = structured_error("pry_x", "invalid_args", "bad url")
        assert result["error"] == {"code": "invalid_args", "message": "bad url"}
        assert result["isError"] is True
        assert json.loads(result["content"][0]["text"]) == {
            "code": "invalid_args",
            "error": "bad url",
        }

    def test_handler_failure_envelope_is_unchanged(self) -> None:
        result = handler_failure("pry_x", RuntimeError("boom"))
        assert json.loads(result["content"][0]["text"]) == {
            "error": "Tool pry_x failed: boom",
            "code": "TOOL_EXECUTION_FAILED",
        }
        assert result["isError"] is True

    def test_import_failure_counts_as_a_handler_failure(self) -> None:
        """A domain package that will not import is reported, not raised."""
        assert ImportError in HANDLER_ERRORS

    def test_sentinel_is_an_exception(self) -> None:
        assert issubclass(ToolNotHandled, Exception)


class TestDispatchOrder:
    def test_chain_order(self) -> None:
        registry = register_standard_executors(ToolRegistry())
        assert list(registry._executors)[:3] == [
            "call_actor_tool",
            "crypto_tool_executor",
            "marketplace_tool_executor",
        ]
        assert list(registry._executors)[3:] == list(_DOMAIN_DISPATCHERS)


class TestResources:
    def test_stats_counts_the_live_registries(self) -> None:
        body = json.loads(resource_text("pry://stats", {"u": {}}, {"p": {}}, {"t": {}}))
        assert body["tools_count"] == 1
        assert body["resources_count"] == 1
        assert body["prompts_count"] == 1

    def test_unknown_uri_gets_the_placeholder(self) -> None:
        assert resource_text("pry://nope", {}, {}, {}) == "Resource pry://nope (placeholder)"

    def test_domains_body_lists_the_static_domains(self) -> None:
        body = json.loads(resource_text("pry://domains", {}, {}, {}))
        assert body["count"] == len(body["domains"]) > 0

    def test_completion_for_max_pages(self) -> None:
        values = completion_values(
            {"type": "ref/prompt", "name": "extract_contacts"}, {"name": "max_pages"}
        )
        assert values == ["10", "20", "50", "100"]

    def test_completion_for_format_falls_through_to_the_mime_list(self) -> None:
        assert completion_values({"type": "ref/tool"}, {"name": "format"}) == [
            "json",
            "csv",
            "markdown",
            "html",
        ]

    def test_prompt_body_keeps_its_wording(self) -> None:
        messages = prompt_messages(
            "research_company", {"company_name": "Acme", "website": "acme.test"}, "Research"
        )
        text = messages[0]["content"]["text"]
        assert text.startswith("Research Acme. Start by scraping acme.test.")
        assert messages[0]["role"] == "user"

    def test_unknown_prompt_uses_the_generic_form(self) -> None:
        messages = prompt_messages("custom", {"a": 1}, "Custom Title")
        assert messages[0]["content"]["text"] == (
            "Execute the Custom Title prompt with arguments: a=1"
        )


class TestResourceHandlerFacade:
    def test_unknown_resource_is_an_invalid_params_error(self) -> None:
        handler = ResourceHandler({}, {})
        assert handler.read_resource("pry://missing")["error"]["code"] == -32602

    def test_unknown_prompt_is_an_invalid_params_error(self) -> None:
        handler = ResourceHandler({}, {})
        assert handler.get_prompt("missing", {})["error"]["code"] == -32602

    def test_read_resource_returns_the_domain_body(self) -> None:
        handler = ResourceHandler({"pry://domains": {"mimeType": "application/json"}}, {})
        response = handler.read_resource("pry://domains")
        assert response["contents"][0]["mimeType"] == "application/json"
        assert "domains" in json.loads(response["contents"][0]["text"])
