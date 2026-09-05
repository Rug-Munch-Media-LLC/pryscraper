"""Pry — pack account binding, key minting, crypto signup (no email).

Account resolution for pack purchases: precedence is explicit ``user_id``,
then ``api_key``'s owner, then the binding stored on the invoice (first
submission wins), then a fresh primary account. Also hosts the crypto
signup surface — an API key + starter credits with no email.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry.commerce import billing_service
from pry.commerce.billing.catalog import STARTER_CREDITS_USD


def _bind_account(invoice: dict[str, Any], *, user_id: str = "", api_key: str = "") -> None:
    """Resolve (and persist on the invoice) the account receiving the credit.

    Precedence: explicit ``user_id``, then ``api_key``'s owner (via
    :func:`pry.core.api_keys_service.authenticate`), then the binding stored
    on the invoice (first submission wins), then a fresh primary account.
    Mutable — writes ``user_id``/``api_key`` onto ``invoice``.
    """
    from pry.core.api_keys_service import PRIMARY_USER_ID, authenticate

    if user_id:
        invoice["user_id"] = user_id
        if api_key:
            invoice["api_key"] = api_key
        return
    if api_key:
        record = authenticate(api_key)
        owner = record["user_id"] if record else PRIMARY_USER_ID
        invoice["user_id"] = owner
        invoice["api_key"] = api_key
        return
    if not invoice.get("user_id"):
        invoice["user_id"] = PRIMARY_USER_ID


def _mint_key(user_id: str, pack_id: str) -> dict[str, Any]:
    """Mint an API key for *user_id* on a successful pack purchase (no email).

    The plaintext is returned once and stored hashed at rest.
    """
    from pry.core.api_keys_service import issue_key

    return issue_key(
        user_id=user_id,
        name=f"pack-{pack_id}-signup" if pack_id else "signup",
        tier="FREE",
        scopes=["scrape", "crawl", "x402", "billing"],
    )


def signup_crypto(user_id: str = "", api_key: str = "") -> dict[str, Any]:
    """Issue a key + starter credits with no email.

    When ``api_key`` is supplied and still active it is returned as-is (no
    duplicate key minted); otherwise a fresh key is minted for ``user_id``
    (or the implicit primary account). Grants ``STARTER_CREDITS_USD`` USD of
    prepaid balance (reason=``grant``, reference=``signup``) exactly once.
    Returns ``{api_key, user_id, created, starter_credits_usd}``.
    """
    if api_key:
        from pry.core.api_keys_service import authenticate

        record = authenticate(api_key)
        if record:
            return {"api_key": api_key, "user_id": record["user_id"], "created": False}
    from pry.core.api_keys_service import PRIMARY_USER_ID

    target_user_id = user_id or PRIMARY_USER_ID
    issued = _mint_key(target_user_id, "signup")
    if not _has_starter_credit(target_user_id):
        billing_service.credit(
            target_user_id, STARTER_CREDITS_USD, reason="grant", reference="signup"
        )
    return {
        "api_key": issued["plaintext"],
        "user_id": target_user_id,
        "created": True,
        "starter_credits_usd": STARTER_CREDITS_USD,
    }


def _has_starter_credit(user_id: str) -> bool:
    """True if this user already consumed the ``signup`` grant (idempotency)."""
    try:
        entries = billing_service.ledger(user_id, limit=100)
    except Exception:  # noqa: BLE001 - never block signup on a ledger error
        return False
    return any(e.get("reference") == "signup" for e in entries)
