"""Pry — DataBus payload normalization helpers.

Pure functions used by the databus bridge to classify scraped results and
extract structured fields (content, blockchain address, chain) from the
pipeline context. No I/O, no module state — safe to import anywhere.
"""

from __future__ import annotations

from typing import Any


def classify_scrape(context: dict[str, Any]) -> str:
    """Classify the scrape result into a DataBus data_type.

    Heuristic-based classification for high-value data types.
    Falls back to "scraped_intel" for general web scraping.
    """
    url = context.get("url", "").lower()
    title = (context.get("title") or "").lower()

    # Scam detection / rugpull reports
    scam_signals = [
        "scam",
        "rug",
        "honeypot",
        "fraud",
        "phishing",
        "suspicious",
        "malicious",
        "fake",
        "ponzi",
    ]
    if any(s in url or s in title for s in scam_signals):
        return "scam_report"

    # Threat intelligence
    threat_signals = [
        "threat",
        "exploit",
        "vulnerability",
        "attack",
        "breach",
        "hack",
        "malware",
        "cve-",
    ]
    if any(s in url or s in title for s in threat_signals):
        return "threat_intel"

    # Blockchain / token data
    blockchain_signals = [
        "token",
        "contract",
        "blockchain",
        "defi",
        "liquidity",
        "pool",
        "swap",
        "dex",
    ]
    if any(s in url or s in title for s in blockchain_signals):
        return "blockchain_data"

    # Entity profiling
    entity_signals = [
        "wallet",
        "address",
        "entity",
        "profile",
        "portfolio",
        "holder",
    ]
    if any(s in url or s in title for s in entity_signals):
        return "entity_profile"

    return "scraped_intel"


def extract_content(context: dict[str, Any]) -> dict[str, Any]:
    """Extract a clean, serializable content dict from the pipeline context."""
    return {
        "title": context.get("title", ""),
        "description": context.get("description", ""),
        "content_preview": (context.get("content") or "")[:5000],
        "quality_score": context.get("quality_score", 0),
        "method": context.get("method", ""),
        "extracted_links": context.get("extracted_links", []),
        "raw_data": context.get("data", {}),
    }


def extract_address(url: str, content: Any) -> str:
    """Try to extract a blockchain address from URL or content."""
    import re

    # Solana address (base58, 32-44 chars)
    sol_match = re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", url)
    if sol_match:
        return sol_match.group(0)

    # EVM address (0x + 40 hex chars)
    evm_match = re.search(r"0x[a-fA-F0-9]{40}", url)
    if evm_match:
        return evm_match.group(0)

    # Check content for first relevant address
    if isinstance(content, dict):
        text = str(content.get("content_preview", ""))
    else:
        text = str(content)[:2000]

    sol_match = re.search(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text)
    if sol_match:
        return sol_match.group(0)
    evm_match = re.search(r"0x[a-fA-F0-9]{40}", text)
    if evm_match:
        return evm_match.group(0)

    return ""


def extract_chain(context: dict[str, Any]) -> str:
    """Try to determine the blockchain chain from context."""
    url = context.get("url", "").lower()
    content = (context.get("content") or "").lower()

    chain_map = {
        "solana": ["solana", "solscan", "spl"],
        "ethereum": ["ethereum", "etherscan", "eth"],
        "bsc": ["bsc", "bscscan", "binance"],
        "base": ["base", "basescan"],
        "polygon": ["polygon", "polygonscan", "matic"],
        "arbitrum": ["arbitrum", "arbiscan"],
        "tron": ["tron", "tronscan", "trx"],
    }

    for chain, signals in chain_map.items():
        if any(s in url or s in content for s in signals):
            return chain

    return ""
