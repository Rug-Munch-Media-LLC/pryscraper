"""Pry — local EIP-3009 payment verification for the EVM self-facilitator."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import Any

from eth_keys import keys  # type: ignore[attr-defined]
from eth_utils import to_checksum_address  # type: ignore[attr-defined]

from pry.payments.x402 import X402_DEFAULT_ASSET
from pry.payments.x402.scheme import normalize_network_id

from .crypto import (
    _nonce_hex,
    _parse_signature,
    _to_int,
    build_transfer_with_authorization_digest,
)
from .evm_common import _pkg
from .networks import _allow_testnets, _chain_id_for, is_testnet_network
from .response import VerifyResult


class EVMVerifyMixin:
    """Local EIP-3009 ``verify`` for :class:`SelfFacilitator`."""

    # ── verify ───────────────────────────────────────────────────────────────

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        """Verify an EVM ``exact`` payment entirely locally.

        ``payment`` must carry:
        - ``network`` (legacy name or CAIP-2), ``asset``, ``amount_usd``
          (minimum required USD);
        - ``authorization``: the EIP-3009 ``transferWithAuthorization``
          fields + signature (``from``, ``to``, ``value``, ``validAfter``,
          ``validBefore``, ``nonce`` and either ``signature`` (65-byte hex) or
          ``v``/``r``/``s``).

        Returns a :class:`VerifyResult`. Replays are rejected via the nonce
        store. The signer recovery, amount, recipient, validity window, chain
        id and asset support are all validated; anything off fails closed.
        """
        network = normalize_network_id(str(payment.get("network") or ""))
        asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()
        try:
            amount_usd = float(payment.get("amount_usd") or 0.0)
        except (TypeError, ValueError):
            amount_usd = 0.0

        # Testnet rejection (fix #2): a free-faucet testnet authorization must
        # never verify as a real payment unless explicitly allowed (dev/test
        # only, debug-gated). Fail closed in production.
        if is_testnet_network(network) and not _allow_testnets():
            return VerifyResult(
                False,
                f"testnet {network!r} rejected on live verify path — "
                "set PRY_X402_ALLOW_TESTNETS=true with DEBUG to enable for dev/test",
                asset=asset,
                network=network,
            )

        entry = _pkg().resolve_asset_entry(network, asset)
        if entry is None:
            return VerifyResult(
                False,
                f"asset {asset!r} not supported on {network}",
                asset=asset,
                network=network,
            )
        verification = entry.get("verification")
        if verification != "eip3009":
            return VerifyResult(
                False,
                f"verification method {verification!r} is not EIP-3009 — "
                "self-facilitator supports eip3009 assets only",
                asset=asset,
                network=network,
            )
        auth = payment.get("authorization")
        if not isinstance(auth, dict) or not auth:
            return VerifyResult(
                False,
                "missing EIP-3009 transferWithAuthorization in payment",
                asset=asset,
                network=network,
            )

        if self.pay_to in _pkg().X402_PLACEHOLDER_WALLETS:
            return VerifyResult(
                False, "server wallet (payTo) not configured", asset=asset, network=network
            )

        chain_id = _chain_id_for(network)
        if chain_id is None:
            return VerifyResult(
                False, f"no EVM chain id known for {network}", asset=asset, network=network
            )
        if auth.get("chainId") is not None:
            try:
                if _to_int(auth["chainId"]) != chain_id:
                    return VerifyResult(
                        False,
                        f"authorization chainId {auth['chainId']} != configured {chain_id}",
                        asset=asset,
                        network=network,
                    )
            except ValueError:
                return VerifyResult(
                    False, "unparseable authorization chainId", asset=asset, network=network
                )

        # Recover the signer first — tampered fields (amount, recipient, …)
        # change the digest and therefore the recovered signer.
        signature = _parse_signature(auth)
        if signature is None:
            return VerifyResult(False, "malformed EIP-3009 signature", asset=asset, network=network)
        try:
            from_address = to_checksum_address(str(auth.get("from") or ""))
        except (ValueError, TypeError):
            return VerifyResult(
                False, "missing/invalid authorization 'from'", asset=asset, network=network
            )
        try:
            digest = build_transfer_with_authorization_digest(
                from_address=from_address,
                to_address=self._normalize_address(str(auth.get("to") or "")),
                value=_to_int(auth.get("value")),
                valid_after=_to_int(auth.get("validAfter") or 0),
                valid_before=_to_int(auth.get("validBefore") or 0),
                nonce=auth.get("nonce"),
                chain_id=chain_id,
                token_address=str(entry["contract"]),
                name=self.domain_name,
                version=self.domain_version,
            )
            recovered = keys.PublicKey.recover_from_msg_hash(digest, signature)
        except (ValueError, TypeError) as e:
            return VerifyResult(
                False, f"cannot verify authorization: {e}", asset=asset, network=network
            )
        recovered_address = to_checksum_address(recovered.to_address())
        if recovered_address != from_address:
            return VerifyResult(
                False,
                f"signer {recovered_address} != authorization from {from_address}",
                asset=asset,
                network=network,
            )

        # Amount: authorized value must be >= the server-side required amount.
        #
        # Price binding (audit #7): when the payment carries an ATTESTED
        # required amount (``attested_required_atomic`` — populated by the
        # enforcement gate only after the echoed 402 body's server attestation
        # verified), that SIGNED ``maxAmountRequired`` is the authoritative
        # required amount for THIS payment. An honest payer who authorized the
        # challenge-quoted amount must not be rejected because the live oracle
        # moved between challenge and payment. Fail-closed is preserved:
        # paying LESS than the attested amount is still underpayment, and
        # overpayment stays allowed. Without an attested amount the previous
        # live-oracle/static comparison applies (backward compatible).
        try:
            value = _to_int(auth.get("value"))
        except ValueError:
            return VerifyResult(
                False, "unparseable authorization value", asset=asset, network=network
            )
        decimals = int(entry.get("decimals", 6))
        attested_atomic = 0
        try:
            attested_atomic = int(payment.get("attested_required_atomic") or 0)
        except (TypeError, ValueError):
            attested_atomic = 0
        if attested_atomic > 0:
            required_atomic = attested_atomic
        else:
            quote = await _pkg().get_asset_usd_price(asset, network)
            if not quote.usd or quote.usd <= 0:
                return VerifyResult(
                    False, f"no USD price available for {asset}", asset=asset, network=network
                )
            required_atomic = (
                round(amount_usd / quote.usd * (10**decimals)) if amount_usd > 0 else 1
            )
        if value < required_atomic:
            return VerifyResult(
                False,
                f"underpayment: authorized {value} < required {required_atomic} atomic {asset}",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Recipient must be our configured payTo wallet.
        try:
            to_address = to_checksum_address(str(auth.get("to") or ""))
        except (ValueError, TypeError):
            return VerifyResult(
                False, "missing/invalid authorization 'to'", asset=asset, network=network
            )
        if to_address != self.pay_to:
            return VerifyResult(
                False,
                f"recipient {to_address} != configured payTo {self.pay_to}",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Validity window (Unix seconds). validBefore == 0 means no expiry
        # (some clients omit it); otherwise must not be in the past.
        now = int(time.time())
        try:
            valid_after = _to_int(auth.get("validAfter") or 0)
            valid_before = _to_int(auth.get("validBefore") or 0)
        except ValueError:
            return VerifyResult(
                False,
                "unparseable authorization validity window",
                signer=recovered_address,
                asset=asset,
                network=network,
            )
        if now < valid_after:
            return VerifyResult(
                False,
                "authorization not valid yet (validAfter in the future)",
                signer=recovered_address,
                asset=asset,
                network=network,
            )
        if valid_before and now >= valid_before:
            return VerifyResult(
                False,
                "authorization expired (validBefore passed)",
                signer=recovered_address,
                asset=asset,
                network=network,
            )

        # Replay protection: the nonce must be unused (per token contract).
        nonce_key = f"{chain_id}:{str(entry['contract']).lower()}:{_nonce_hex(auth.get('nonce'))}"
        if not self.nonces.mark_used(nonce_key):
            return VerifyResult(
                False,
                "nonce already used (replay)",
                signer=recovered_address,
                amount_atomic=value,
                asset=asset,
                network=network,
            )

        return VerifyResult(
            True,
            "",
            signer=recovered_address,
            amount_atomic=value,
            asset=asset,
            network=network,
        )
