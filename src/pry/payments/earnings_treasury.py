"""Pry — treasury balance probes.

On-chain balance queries for the three operator treasuries (EVM / Solana /
TRON) via free public endpoints. Treasury queries are resilient by design:
10s timeout, 5-minute cache, and every failure degrades to an ``error`` entry —
they can never crash the caller.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from pry.payments.earnings_cache import TREASURY_CACHE_TTL_S, _cached, _store

logger = logging.getLogger(__name__)

#: Operator treasuries (public receiving addresses — safe to embed).
TREASURY_EVM = "0x1E3AC01d0fdb976179790BDD02823196A92705C9"
TREASURY_SOLANA = "G1uZFfsdxK2PuH2Em5LhRkEcptxHWe4vy5BZak67QyKv"
TREASURY_TRON = "TYSWXWr24QTe3c99V9dtzhe1aZTneE261p"

#: Treasury query tuning.
TREASURY_TIMEOUT_S = 10.0

#: Free public endpoints (no key required except Etherscan, which is optional —
#: when absent we fall back to a public RPC for the native balance).
ETHERSCAN_API = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY_ENV = "ETHERSCAN_API_KEY"
EVM_PUBLIC_RPC = "https://eth.llamarpc.com"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
TRONGRID_API = "https://api.trongrid.io"

#: USDC contract on Ethereum mainnet (for the Etherscan tokenbalance probe).
USDC_ETHEREUM = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WEI = 10**18
LAMPORTS = 10**9
#: 6-decimal stablecoin atomic units (USDC).
STABLE_ATOMIC = 10**6

# ── Treasury balance cache (module-level, shared across instances) ──────────
_treasury_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class TreasuryMixin:
    """Treasury balance probes (each fully isolated)."""

    def get_treasury_balances(self) -> dict[str, Any]:
        """On-chain balances for the three operator treasuries.

        Resilient: 10s timeout, 5-minute cache, per-chain error isolation.
        Never raises.
        """
        return {
            "evm": self._evm_balance(),
            "solana": self._solana_balance(),
            "tron": self._tron_balance(),
            "cached_ttl_s": TREASURY_CACHE_TTL_S,
        }

    def _evm_balance(self) -> dict[str, Any]:
        cache_key = f"evm:{TREASURY_EVM}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            api_key = os.getenv(ETHERSCAN_API_KEY_ENV, "")
            native = self._evm_etherscan(api_key) if api_key else self._evm_rpc_native()
            usdc = self._evm_usdc(api_key) if api_key else None
            result: dict[str, Any] = {
                "address": TREASURY_EVM,
                "native_balance": native,
                **({"usdc_balance": usdc} if usdc is not None else {}),
            }
            return _store(cache_key, result)
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "TreasuryMixin._evm_balance"},
            )
            return {"address": TREASURY_EVM, "error": str(exc)}

    def _evm_etherscan(self, api_key: str) -> float:
        resp = httpx.get(
            ETHERSCAN_API,
            params={
                "module": "account",
                "action": "balance",
                "address": TREASURY_EVM,
                "tag": "latest",
                "apikey": api_key,
            },
            timeout=TREASURY_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("status")) != "1":
            raise ValueError(f"etherscan error: {data.get('result')}")
        return round(int(data["result"]) / WEI, 8)

    def _evm_rpc_native(self) -> float:
        resp = httpx.post(
            EVM_PUBLIC_RPC,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBalance",
                "params": [TREASURY_EVM, "latest"],
            },
            timeout=TREASURY_TIMEOUT_S,
        )
        resp.raise_for_status()
        hex_balance = resp.json()["result"]
        return round(int(hex_balance, 16) / WEI, 8)

    def _evm_usdc(self, api_key: str) -> float | None:
        """None means "Etherscan had no answer", never "the probe failed".

        The caller omits ``usdc_balance`` on None, so a failed probe returning
        it would read as a drained treasury. Errors propagate instead."""
        resp = httpx.get(
            ETHERSCAN_API,
            params={
                "module": "account",
                "action": "tokenbalance",
                "contractaddress": USDC_ETHEREUM,
                "address": TREASURY_EVM,
                "tag": "latest",
                "apikey": api_key,
            },
            timeout=TREASURY_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("status")) != "1":
            return None
        return round(int(data["result"]) / STABLE_ATOMIC, 6)

    def _solana_balance(self) -> dict[str, Any]:
        cache_key = f"sol:{TREASURY_SOLANA}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            resp = httpx.post(
                SOLANA_RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [TREASURY_SOLANA],
                },
                timeout=TREASURY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise ValueError(f"solana rpc error: {data['error']}")
            lamports = int(data["result"]["value"])
            return _store(
                cache_key,
                {
                    "address": TREASURY_SOLANA,
                    "native_balance": round(lamports / LAMPORTS, 8),
                },
            )
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "TreasuryMixin._solana_balance"},
            )
            return {"address": TREASURY_SOLANA, "error": str(exc)}

    def _tron_balance(self) -> dict[str, Any]:
        cache_key = f"trx:{TREASURY_TRON}"
        if (hit := _cached(cache_key)) is not None:
            return hit
        try:
            resp = httpx.get(
                f"{TRONGRID_API}/v1/accounts/{TREASURY_TRON}",
                timeout=TREASURY_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("data") or []
            sun = int(accounts[0].get("balance", 0)) if accounts else 0
            return _store(
                cache_key,
                {
                    "address": TREASURY_TRON,
                    "native_balance": round(sun / 1_000_000, 8),
                },
            )
        except (ImportError, OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "TreasuryMixin._tron_balance"},
            )
            return {"address": TREASURY_TRON, "error": str(exc)}
