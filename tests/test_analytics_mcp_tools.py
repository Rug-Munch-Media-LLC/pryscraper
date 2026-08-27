# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for payment analytics and dynamic MCP tools."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime

from payments.analytics import PaymentAnalytics


class TestPaymentAnalytics:
    """Test payment analytics engine."""

    def _create_test_files(self) -> tuple[str, str]:
        tmpdir = tempfile.mkdtemp()
        payments_file = os.path.join(tmpdir, "payments.jsonl")
        settlements_file = os.path.join(tmpdir, "settlements.jsonl")
        now = datetime.now(UTC)
        payments = [
            {
                "payment_id": "pay_1",
                "amount_usd": 1.0,
                "verified": True,
                "network": "base",
                "asset": "USDC",
                "signer": "0xabc",
                "verified_at": now.isoformat(),
            },
            {
                "payment_id": "pay_2",
                "amount_usd": 2.0,
                "verified": True,
                "network": "solana",
                "asset": "SOL",
                "signer": "0xabc",
                "verified_at": now.isoformat(),
            },
            {
                "payment_id": "pay_3",
                "amount_usd": 0.5,
                "verified": False,
                "network": "base",
                "asset": "USDC",
                "signer": "0xdef",
                "verified_at": now.isoformat(),
            },
        ]
        with open(payments_file, "w") as f:
            for p in payments:
                f.write(json.dumps(p) + "\n")
        return payments_file, settlements_file

    def test_get_revenue_summary(self) -> None:
        payments_file, settlements_file = self._create_test_files()
        analytics = PaymentAnalytics(payments_file, settlements_file)
        summary = analytics.get_revenue_summary(30)
        assert summary["total_revenue_usd"] == 3.5
        assert summary["successful_payments"] == 2
        assert summary["failed_payments"] == 1

    def test_get_top_payers(self) -> None:
        payments_file, settlements_file = self._create_test_files()
        analytics = PaymentAnalytics(payments_file, settlements_file)
        top = analytics.get_top_payers(10)
        assert len(top) == 2
        assert top[0]["payer"] == "0xabc"
        assert top[0]["total_usd"] == 3.0

    def test_get_network_breakdown(self) -> None:
        payments_file, settlements_file = self._create_test_files()
        analytics = PaymentAnalytics(payments_file, settlements_file)
        breakdown = analytics.get_network_breakdown(30)
        assert "base" in breakdown
        assert "solana" in breakdown
        assert breakdown["base"]["count"] == 2

    def test_get_asset_breakdown(self) -> None:
        payments_file, settlements_file = self._create_test_files()
        analytics = PaymentAnalytics(payments_file, settlements_file)
        breakdown = analytics.get_asset_breakdown(30)
        assert "USDC" in breakdown
        assert "SOL" in breakdown
        assert breakdown["USDC"]["count"] == 2

    def test_get_daily_revenue(self) -> None:
        payments_file, settlements_file = self._create_test_files()
        analytics = PaymentAnalytics(payments_file, settlements_file)
        daily = analytics.get_daily_revenue(30)
        assert len(daily) == 1
        assert daily[0]["revenue_usd"] == 3.5

    def test_empty_files(self) -> None:
        tmpdir = tempfile.mkdtemp()
        analytics = PaymentAnalytics(
            os.path.join(tmpdir, "nonexistent.jsonl"), os.path.join(tmpdir, "nonexistent.jsonl")
        )
        summary = analytics.get_revenue_summary(30)
        assert summary["total_revenue_usd"] == 0
        assert summary["successful_payments"] == 0

    def test_analytics_instance(self) -> None:
        a1 = PaymentAnalytics("/tmp/a.jsonl", "/tmp/b.jsonl")
        assert isinstance(a1, PaymentAnalytics)


class TestDynamicMCPTools:
    """Test dynamic MCP tool generation."""

    def test_discover_api_tools_returns_list(self) -> None:
        from pry.api.mcp_tools import discover_api_tools

        tools = discover_api_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tool_has_required_fields(self) -> None:
        from pry.api.mcp_tools import discover_api_tools

        tools = discover_api_tools()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_path_to_tool_name(self) -> None:
        from pry.api.mcp_tools import _path_to_tool_name

        assert _path_to_tool_name("/v1/scrape", "POST") == "pry_scrape"
        assert _path_to_tool_name("/v1/crawl", "POST") == "pry_crawl"

    def test_type_to_json_schema(self) -> None:
        from pry.api.mcp_tools import _type_to_json_schema

        assert _type_to_json_schema(int) == "integer"
        assert _type_to_json_schema(float) == "number"
        assert _type_to_json_schema(bool) == "boolean"
        assert _type_to_json_schema(str) == "string"
