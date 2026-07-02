# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for AI agent plugin."""

from ai_plugin import get_gpt_action_manifest, get_mcp_server_config, get_openapi_spec


def test_openapi_spec_valid() -> None:
    spec = get_openapi_spec()
    assert "openapi" in spec
    assert spec["info"]["title"] == "Pry Web Intelligence API"
    assert "/v1/scrape" in spec["paths"]
    assert "/health" in spec["paths"]


def test_gpt_manifest_has_required_fields() -> None:
    manifest = get_gpt_action_manifest()
    assert manifest["schema_version"] == "v1"
    assert "description_for_human" in manifest
    assert "api" in manifest
    assert manifest["api"]["type"] == "openapi"


def test_mcp_config_has_pry() -> None:
    config = get_mcp_server_config()
    assert "pry_scraper" in config
    assert config["pry_scraper"]["type"] == "local"
