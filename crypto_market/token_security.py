# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Token security / rug-check scanner backed by GoPlus Security's free API.

Primary source: GoPlus Security ``token_security`` endpoint
(https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses=…)
— the free tier requires no API key. Local heuristics provide a degraded
fallback when GoPlus is unreachable, the chain is unsupported (e.g. Solana,
which GoPlus does not cover for this endpoint), or the token is not listed.

The public entrypoint is :func:`scan_token` — an async function that never
raises. It returns a flat dict:

    {
        "chain": str,
        "address": str,
        "risk_score": int,        # 0-100, higher = riskier
        "verdict": str,           # "safe" | "caution" | "high_risk" | "unknown"
        "flags": list[str],       # human-readable risk flags
        "checks": {               # structured per-check booleans / float
            "honeypot": bool,
            "mint_authority": bool,
            "lp_locked": bool,
            "owner_renounced": bool,
            "holder_concentration": float,   # top-holder percent (0-100)
            "proxy_contract": bool,
            "source_code_verified": bool,
        },
        "source": str,            # "goplus" | "heuristic" | "none"
    }

On catastrophic failure the dict is returned with ``risk_score: -1``,
``verdict: "unknown"``, ``checks: {}`` and ``source: "none"``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GOPLUS_BASE_URL = "https://api.gopluslabs.io/api/v1/token_security"
GOPLUS_TIMEOUT = httpx.Timeout(10.0)

# Chain name -> GoPlus chain id (https://docs.gopluslabs.io/reference/chainid)
_EVM_CHAIN_IDS: dict[str, str] = {
    "ethereum": "1",
    "eth": "1",
    "mainnet": "1",
    "bsc": "56",
    "bnb": "56",
    "binance": "56",
    "binance-smart-chain": "56",
    "arbitrum": "42161",
    "arb": "42161",
    "base": "8453",
    "polygon": "137",
    "poly": "137",
    "matic": "137",
}
_SOLANA_NAMES = frozenset({"solana", "sol", "solana-mainnet", "solana-mainnet-beta"})
_NUMERIC_EVM_CHAIN_IDS = frozenset({"1", "56", "42161", "8453", "137"})

_EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_BASE58_CHARS = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")

_EMPTY_CHECKS: dict[str, bool | float] = {
    "honeypot": False,
    "mint_authority": False,
    "lp_locked": False,
    "owner_renounced": False,
    "holder_concentration": 0.0,
    "proxy_contract": False,
    "source_code_verified": False,
}

# Human-readable flags appended on the heuristic fallback path.
_HEURISTIC_FLAGS: dict[str, str] = {
    "unsupported": "chain not supported by security provider",
    "not_found": "token not found in security provider",
    "unreachable": "security provider unreachable",
}


def _resolve_chain(chain: str) -> tuple[str | None, str | None]:
    """Map a chain name to ``(kind, goplus_chain_id)``.

    ``kind`` is ``"evm"`` or ``"solana"``; the GoPlus chain id is ``None`` for
    Solana and for unsupported chains.
    """
    key = chain.strip().lower()
    if key in _SOLANA_NAMES:
        return "solana", None
    if key in _EVM_CHAIN_IDS:
        return "evm", _EVM_CHAIN_IDS[key]
    if key in _NUMERIC_EVM_CHAIN_IDS:
        return "evm", key
    return None, None


def _is_plausible_address(chain_kind: str | None, address: str) -> bool:
    """Cheap syntactic sanity check for an address on the given chain kind."""
    if chain_kind == "evm":
        return bool(_EVM_ADDRESS_RE.match(address))
    if chain_kind == "solana":
        return 32 <= len(address) <= 44 and all(c in _BASE58_CHARS for c in address)
    return False


def _is_zero_address(owner: object) -> bool:
    """Treat null / empty / burn-style owner addresses as renounced."""
    if owner is None:
        return True
    value = str(owner).strip().lower()
    return value in {"", "0", "null", "none", "0x", "0x0", "0x00", "0x" + "0" * 40}


def _top_holder_percent(holders: object) -> float:
    """Largest single-holder percentage from GoPlus ``holders`` list."""
    if not isinstance(holders, list):
        return 0.0
    best = 0.0
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        raw = holder.get("percent")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        best = max(best, value)
    return round(best, 2)


def _parse_lp_state(token: dict[str, Any]) -> tuple[bool, bool]:
    """Return ``(lp_present, lp_locked)`` from GoPlus ``lp_holders``."""
    lp_holders = token.get("lp_holders")
    if not isinstance(lp_holders, list) or not lp_holders:
        return False, False
    locked = any(
        isinstance(holder, dict) and holder.get("is_locked") == "1" for holder in lp_holders
    )
    return True, locked


def _parse_owner_renounced(token: dict[str, Any]) -> bool:
    """Owner renounced when GoPlus says so or the owner is a zero address."""
    if token.get("is_owner_renounced") == "1":
        return True
    return _is_zero_address(token.get("owner_address"))


def _derive_verdict(score: int) -> str:
    """Map a risk score to a verdict: <40 safe, 40-70 caution, >70 high_risk."""
    if score < 40:
        return "safe"
    if score <= 70:
        return "caution"
    return "high_risk"


def _build_flags(
    *,
    is_honeypot: bool,
    mintable: bool,
    blacklisted: bool,
    lp_present: bool,
    lp_locked: bool,
    owner_renounced: bool,
    proxy_contract: bool,
    verified: bool,
    top_holder: float,
) -> list[str]:
    """Human-readable risk flags derived from the parsed checks."""
    flags: list[str] = []
    if is_honeypot:
        flags.append("honeypot")
    if mintable:
        flags.append("mint authority active")
    if blacklisted:
        flags.append("token blacklisted")
    if lp_present and not lp_locked:
        flags.append("LP not locked")
    if not owner_renounced:
        flags.append("owner not renounced")
    if proxy_contract:
        flags.append("proxy contract")
    if not verified:
        flags.append("contract source not verified")
    if top_holder >= 30.0:
        flags.append("high holder concentration")
    return flags


def _build_goplus_result(chain: str, address: str, token: dict[str, Any]) -> dict[str, Any]:
    """Build the scan result from a parsed GoPlus token payload."""
    is_honeypot = token.get("is_honeypot") == "1"
    mintable = token.get("is_mintable") == "1"
    blacklisted = token.get("is_blacklisted") == "1"

    lp_present, lp_locked = _parse_lp_state(token)
    owner_renounced = _parse_owner_renounced(token)
    top_holder = _top_holder_percent(token.get("holders"))
    proxy_contract = token.get("is_proxy") == "1"
    verified = token.get("is_open_source") == "1" or token.get("is_verified") == "1"

    checks: dict[str, bool | float] = {
        "honeypot": is_honeypot,
        "mint_authority": mintable,
        "lp_locked": lp_locked,
        "owner_renounced": owner_renounced,
        "holder_concentration": top_holder,
        "proxy_contract": proxy_contract,
        "source_code_verified": verified,
    }

    score = 0
    if is_honeypot:
        score += 60
    if mintable:
        score += 25
    if blacklisted:
        score += 20
    if lp_present and not lp_locked:
        score += 20
    if not owner_renounced:
        score += 15
    if proxy_contract:
        score += 15
    if not verified:
        score += 10
    if top_holder >= 50.0:
        score += 25
    elif top_holder >= 30.0:
        score += 15
    score = min(100, score)

    flags = _build_flags(
        is_honeypot=is_honeypot,
        mintable=mintable,
        blacklisted=blacklisted,
        lp_present=lp_present,
        lp_locked=lp_locked,
        owner_renounced=owner_renounced,
        proxy_contract=proxy_contract,
        verified=verified,
        top_holder=top_holder,
    )

    return {
        "chain": chain,
        "address": address,
        "risk_score": score,
        "verdict": _derive_verdict(score),
        "flags": flags,
        "checks": checks,
        "source": "goplus",
    }


def _heuristic_result(chain: str, address: str, reason: str) -> dict[str, Any]:
    """Degraded local-only result when GoPlus data is unavailable."""
    chain_kind, _ = _resolve_chain(chain)
    if not _is_plausible_address(chain_kind, address):
        return {
            "chain": chain,
            "address": address,
            "risk_score": 90,
            "verdict": "high_risk",
            "flags": ["invalid address format", "no external security data available"],
            "checks": dict(_EMPTY_CHECKS),
            "source": "heuristic",
        }
    return {
        "chain": chain,
        "address": address,
        "risk_score": 50,
        "verdict": "caution",
        "flags": ["no external security data available", _HEURISTIC_FLAGS[reason]],
        "checks": dict(_EMPTY_CHECKS),
        "source": "heuristic",
    }


def _unknown_result(chain: str, address: str) -> dict[str, Any]:
    """Last-resort result for catastrophic internal failure (never raises)."""
    return {
        "chain": chain,
        "address": address,
        "risk_score": -1,
        "verdict": "unknown",
        "flags": [],
        "checks": {},
        "source": "none",
    }


async def _fetch_goplus(chain_id: str, address: str) -> dict[str, Any] | None:
    """Query GoPlus and return the token payload, or ``None`` when missing."""
    key = address.lower()
    params = {"contract_addresses": key}
    async with httpx.AsyncClient(timeout=GOPLUS_TIMEOUT) as client:
        response = await client.get(f"{GOPLUS_BASE_URL}/{chain_id}", params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 1:
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or not result:
        return None
    token = result.get(key)
    if token is None:
        token = next(iter(result.values()))
    if not isinstance(token, dict):
        return None
    return token


async def _scan_token(chain: str, address: str) -> dict[str, Any]:
    """Run the scan: GoPlus first, heuristic fallback on any GoPlus failure."""
    chain_kind, chain_id = _resolve_chain(chain)
    if chain_id is None or not _is_plausible_address(chain_kind, address):
        return _heuristic_result(chain, address, "unsupported")

    try:
        token = await _fetch_goplus(chain_id, address)
    except httpx.HTTPError:
        logger.warning("goplus request failed", exc_info=True)
        return _heuristic_result(chain, address, "unreachable")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        logger.warning("goplus response unparsable: %s", exc)
        return _heuristic_result(chain, address, "unreachable")

    if token is None:
        return _heuristic_result(chain, address, "not_found")
    return _build_goplus_result(chain, address, token)


async def scan_token(chain: str, address: str) -> dict[str, Any]:
    """Scan a token for rug/security risk. Never raises.

    Primary source is the GoPlus Security free API. When GoPlus is
    unreachable, the chain is unsupported, or the token is missing, a local
    heuristic result (``source: "heuristic"``) is returned. Only catastrophic
    unexpected failures produce the ``source: "none"`` unknown result.
    """
    try:
        return await _scan_token(chain, address)
    except Exception:  # logged below — intentional last-resort safety net
        logger.exception("token security scan crashed")
        return _unknown_result(chain, address)
