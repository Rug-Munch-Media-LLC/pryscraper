"""Pry — attested price-binding extraction over the x402 payment-required body.

Extracted from ``attestation_verify`` (behavior-preserving): read the SIGNED
``maxAmountRequired`` of the accept matching a normalized (network, asset) pair.
Callers MUST verify the body's attestation first; this helper does no crypto.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from .networks import normalize_network_id


def attested_max_amount_required(
    body: dict[str, Any],
    network: str,
    asset: str,
) -> int:
    """Extract the attested ``maxAmountRequired`` (atomic) for (network, asset).

    Price binding (audit #7): the ``maxAmountRequired`` inside a VERIFIED
    server attestation is the authoritative required amount for THAT payment —
    it was signed at challenge-issuance time, so an honest payer who
    authorized the quoted amount must not be re-priced against a live oracle
    that moved in between. Callers MUST verify the body's attestation
    (:func:`verify_payment_required_attestation`) BEFORE trusting the value
    returned here; this helper performs no crypto of its own.

    Returns the positive atomic amount of the accept matching the normalized
    (network, asset) pair, or 0 when the body is unattested / unusable / no
    accept matches (callers then fall back to the live-quote comparison).
    """
    if not isinstance(body, dict) or not isinstance(body.get("attestation"), dict):
        return 0
    network_id = normalize_network_id(str(network or ""))
    asset_upper = str(asset or "").upper()
    accepts = body.get("accepts")
    if not isinstance(accepts, list):
        return 0
    for accept in accepts:
        if not isinstance(accept, dict):
            continue
        if normalize_network_id(str(accept.get("network", ""))) != network_id:
            continue
        if str(accept.get("asset", "")).upper() != asset_upper:
            continue
        try:
            value = int(str(accept.get("maxAmountRequired", "")))
        except (ValueError, TypeError):
            return 0
        return value if value > 0 else 0
    return 0
