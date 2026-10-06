"""Pry — self-facilitator chain-id resolution + testnet rejection."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os

from pry.payments.x402 import X402_DEBUG_MODE
from pry.payments.x402.scheme import normalize_network_id

logger = logging.getLogger(__name__)

# CAIP-2 / legacy network name -> EVM chain id (used for the EIP-712 domain
# and the signed transaction's EIP-155 v). eip155:NNNN ids not listed here
# are parsed directly from the CAIP-2 suffix.
CHAIN_ID_BY_NETWORK: dict[str, int] = {
    "eip155:8453": 8453,
    "base": 8453,
    "eip155:1": 1,
    "ethereum": 1,
    "eip155:42161": 42161,
    "arbitrum": 42161,
    "eip155:10": 10,
    "optimism": 10,
    "eip155:137": 137,
    "polygon": 137,
    "eip155:56": 56,
    "bnb": 56,
    "eip155:43114": 43114,
    "avalanche": 43114,
    "eip155:84532": 84532,
    "base-sepolia": 84532,
}

# ── Testnet rejection (fix #2) ────────────────────────────────────────────────
# Free-faucet testnet USDC must NEVER verify as a real payment on the live
# path. Any network whose normalized id or chain id lands in these sets is
# rejected unless PRY_X402_ALLOW_TESTNETS is explicitly enabled (and gated by
# DEBUG — same convention as X402_OFFLINE_MODE). Mirrors the codebase's
# existing "dev-only bypass requires DEBUG" rule so production never accepts
# a testnet.
TESTNET_NETWORK_IDS: frozenset[str] = frozenset(
    {
        "base-sepolia",
        "eip155:84532",
        "sepolia",
        "eip155:11155111",
        "eip155:11155420",  # optimistic sepolia
        "eip155:80002",  # polygon amoy
        "eip155:421614",  # arbitrum sepolia
        "eip155:97",  # bsc testnet
        "eip155:43113",  # avalanche fuji
        "eip155:17000",  # holesky
    }
)
TESTNET_CHAIN_IDS: frozenset[int] = frozenset(
    {
        84532,
        11155111,
        11155420,
        80002,
        421614,
        97,
        43113,
        17000,
    }
)


def _allow_testnets() -> bool:
    """Whether testnet chains are permitted on the live verify/settle path.

    Dev/test only — requires BOTH PRY_X402_ALLOW_TESTNETS=true AND a debug
    flag. Production (no debug flag) always rejects testnets.
    """
    return (
        os.getenv("PRY_X402_ALLOW_TESTNETS", "false").lower() in ("1", "true", "yes")
        and X402_DEBUG_MODE
    )


def is_testnet_network(network: str) -> bool:
    """True when ``network`` (legacy name or CAIP-2 id) is a known testnet.

    Checks the normalized id and the resolved chain id so both ``base-sepolia``
    and ``eip155:84532`` are caught. Unknown networks are NOT treated as
    testnets by this check alone (callers additionally require the network to
    be a supported EVM chain before verifying).
    """
    if not network:
        return False
    network_id = normalize_network_id(network)
    if network_id in TESTNET_NETWORK_IDS:
        return True
    chain_id = _chain_id_for(network)
    return chain_id is not None and chain_id in TESTNET_CHAIN_IDS


def _chain_id_for(network: str) -> int | None:
    """Resolve the EVM chain id for a legacy name or CAIP-2 network id."""
    network_id = normalize_network_id(network)
    if network_id in CHAIN_ID_BY_NETWORK:
        return CHAIN_ID_BY_NETWORK[network_id]
    if network_id.startswith("eip155:"):
        try:
            return int(network_id.split(":", 1)[1])
        except ValueError as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "_chain_id_for"},
            )
            return None
    return None
