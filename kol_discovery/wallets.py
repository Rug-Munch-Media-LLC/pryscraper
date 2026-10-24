"""Explicit-only wallet attribution gate.

Two independent refusals, both tested:

1. ``claim_from_bio`` — builds a ``declared`` claim only from a *labelled*
   wallet phrase in the bio. An unlabelled base58 string is a token contract.
2. ``claim_from_leaderboard`` — a third-party board pairing handle<->wallet is
   ``inferred`` at best; it needs an evidence URL and is never factual.
"""

from __future__ import annotations

from .bios import WALLET_LABEL_RE
from .models import Attribution, InvalidAddress, UnstatedWalletError, WalletClaim, detect_chain


def claim_from_bio(bio: str, address: str, evidence_url: str = "") -> WalletClaim:
    """Attach ``address`` to a KOL only if the bio labels it as a wallet."""
    target = (address or "").strip()
    if not target:
        raise UnstatedWalletError("empty address")
    chain = detect_chain(target)
    for match in WALLET_LABEL_RE.finditer(bio or ""):
        if match.group(1).casefold() == target.casefold():
            return WalletClaim(
                chain=chain,
                address=target,
                source="bio",
                attribution="declared",
                evidence=match.group(0).strip(),
                evidence_url=evidence_url,
            )
    raise UnstatedWalletError(
        "bio does not state this address as a wallet "
        f"(unlabelled addresses are treated as token contracts): {target}"
    )


def claim_from_leaderboard(address: str, evidence_url: str, handle: str) -> WalletClaim:
    """Third-party board pairing — recorded, flagged inferred, never fact."""
    if not evidence_url.strip():
        raise UnstatedWalletError("leaderboard claim requires the fetched URL as evidence")
    return WalletClaim(
        chain=detect_chain(address),
        address=address.strip(),
        source="leaderboard",
        attribution="inferred",
        evidence=f"board pairs wallet with @{handle}",
        evidence_url=evidence_url,
    )


def merge_claims(existing: list[WalletClaim], incoming: WalletClaim) -> list[WalletClaim]:
    """Dedupe by wallet key; a factual claim upgrades an inferred one."""
    kept: list[WalletClaim] = []
    replaced = False
    for claim in existing:
        if claim.key != incoming.key:
            kept.append(claim)
            continue
        if claim.is_fact and not incoming.is_fact:
            kept.append(claim)  # never downgrade a statement to a guess
            replaced = True
        elif incoming.is_fact and not claim.is_fact:
            kept.append(incoming)  # upgrade guess -> statement
            replaced = True
        else:
            kept.append(claim)
            replaced = True
    if not replaced:
        kept.append(incoming)
    return kept


__all__ = [
    "Attribution",
    "InvalidAddress",
    "UnstatedWalletError",
    "claim_from_bio",
    "claim_from_leaderboard",
    "merge_claims",
]
