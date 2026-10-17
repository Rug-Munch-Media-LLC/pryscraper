# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the GoPlus-backed token security / rug-check scanner."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

import crypto_market.token_security as token_security
from crypto_market.token_security import _derive_verdict, scan_token

HONEYPOT_ADDRESS = "0x" + "1" * 40
SAFE_ADDRESS = "0x" + "2" * 40

HONEYPOT_PAYLOAD: dict[str, Any] = {
    "code": 1,
    "message": "OK",
    "result": {
        HONEYPOT_ADDRESS: {
            "is_honeypot": "1",
            "is_mintable": "1",
            "is_blacklisted": "0",
            "is_open_source": "0",
            "is_proxy": "0",
            "is_owner_renounced": "0",
            "owner_address": "0x0000000000000000000000000000000000dEaD",
            "holders": [
                {"address": "0xaaa", "percent": "80"},
                {"address": "0xbbb", "percent": "20"},
            ],
            "lp_holders": [],
        }
    },
}

SAFE_PAYLOAD: dict[str, Any] = {
    "code": 1,
    "message": "OK",
    "result": {
        SAFE_ADDRESS: {
            "is_honeypot": "0",
            "is_mintable": "0",
            "is_blacklisted": "0",
            "is_open_source": "1",
            "is_proxy": "0",
            "is_owner_renounced": "1",
            "owner_address": "0x0000000000000000000000000000000000000000",
            "holders": [{"address": "0xccc", "percent": "5.2"}],
            "lp_holders": [{"address": "0xpool", "is_locked": "1", "locked_detail": "90 days"}],
        }
    },
}


@respx.mock
async def test_scan_token_honeypot_high_risk() -> None:
    """A honeypot token scores 100 / high_risk with the expected flags."""
    respx.get(url__startswith="https://api.gopluslabs.io/api/v1/token_security/56").mock(
        return_value=httpx.Response(200, json=HONEYPOT_PAYLOAD)
    )
    result = await scan_token("bsc", HONEYPOT_ADDRESS)

    assert result["chain"] == "bsc"
    assert result["address"] == HONEYPOT_ADDRESS
    assert result["source"] == "goplus"
    assert result["risk_score"] == 100
    assert result["verdict"] == "high_risk"

    checks = result["checks"]
    assert checks["honeypot"] is True
    assert checks["mint_authority"] is True
    assert checks["lp_locked"] is False
    assert checks["owner_renounced"] is False
    assert checks["holder_concentration"] == 80.0
    assert checks["proxy_contract"] is False
    assert checks["source_code_verified"] is False

    for flag in (
        "honeypot",
        "mint authority active",
        "owner not renounced",
        "contract source not verified",
        "high holder concentration",
    ):
        assert flag in result["flags"]


@respx.mock
async def test_scan_token_safe_token() -> None:
    """A clean token scores 0 / safe with empty flags."""
    respx.get(url__startswith="https://api.gopluslabs.io/api/v1/token_security/1").mock(
        return_value=httpx.Response(200, json=SAFE_PAYLOAD)
    )
    result = await scan_token("ethereum", SAFE_ADDRESS)

    assert result["source"] == "goplus"
    assert result["risk_score"] == 0
    assert result["verdict"] == "safe"
    assert result["flags"] == []

    checks = result["checks"]
    assert checks["honeypot"] is False
    assert checks["mint_authority"] is False
    assert checks["lp_locked"] is True
    assert checks["owner_renounced"] is True
    assert checks["holder_concentration"] == 5.2
    assert checks["proxy_contract"] is False
    assert checks["source_code_verified"] is True


@respx.mock
async def test_scan_token_missing_falls_back_to_heuristic() -> None:
    """A 200 with code != 1 (token not listed) returns a heuristic caution."""
    respx.get(url__startswith="https://api.gopluslabs.io/api/v1/token_security/1").mock(
        return_value=httpx.Response(200, json={"code": 0, "message": "NOT_FOUND", "result": {}})
    )
    result = await scan_token("ethereum", SAFE_ADDRESS)

    assert result["source"] == "heuristic"
    assert result["risk_score"] == 50
    assert result["verdict"] == "caution"
    assert "no external security data available" in result["flags"]
    assert "token not found in security provider" in result["flags"]
    assert result["checks"]["holder_concentration"] == 0.0


@respx.mock
async def test_scan_token_goplus_unreachable_falls_back_to_heuristic() -> None:
    """A network error on the GoPlus call degrades to a heuristic result."""
    respx.get(url__startswith="https://api.gopluslabs.io/api/v1/token_security/56").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = await scan_token("bsc", HONEYPOT_ADDRESS)

    assert result["source"] == "heuristic"
    assert result["risk_score"] == 50
    assert result["verdict"] == "caution"
    assert "security provider unreachable" in result["flags"]


async def test_scan_token_solana_heuristic_path() -> None:
    """Solana is not on GoPlus for this endpoint → heuristic caution."""
    sol_address = "So11111111111111111111111111111111111111112"
    result = await scan_token("solana", sol_address)

    assert result["source"] == "heuristic"
    assert result["risk_score"] == 50
    assert result["verdict"] == "caution"
    assert "chain not supported by security provider" in result["flags"]
    expected = {
        "honeypot": False,
        "mint_authority": False,
        "lp_locked": False,
        "owner_renounced": False,
        "holder_concentration": 0.0,
        "proxy_contract": False,
        "source_code_verified": False,
    }
    assert result["checks"] == expected


async def test_scan_token_invalid_address_heuristic_high_risk() -> None:
    """A malformed address gets a heuristic high-risk verdict, no network."""
    result = await scan_token("ethereum", "not-an-address")

    assert result["source"] == "heuristic"
    assert result["risk_score"] == 90
    assert result["verdict"] == "high_risk"
    assert "invalid address format" in result["flags"]


async def test_scan_token_graceful_unknown_on_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected internal error returns the unknown/none contract — no raise."""

    async def _boom(chain_id: str, address: str) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(token_security, "_fetch_goplus", _boom)
    result = await scan_token("ethereum", SAFE_ADDRESS)

    assert result["chain"] == "ethereum"
    assert result["address"] == SAFE_ADDRESS
    assert result["risk_score"] == -1
    assert result["verdict"] == "unknown"
    assert result["flags"] == []
    assert result["checks"] == {}
    assert result["source"] == "none"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "safe"),
        (39, "safe"),
        (40, "caution"),
        (70, "caution"),
        (71, "high_risk"),
        (100, "high_risk"),
    ],
)
def test_derive_verdict_boundaries(score: int, expected: str) -> None:
    """Verdict thresholds: <40 safe, 40-70 caution, >70 high_risk."""
    assert _derive_verdict(score) == expected
