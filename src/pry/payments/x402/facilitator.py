"""Pry — x402 facilitator router.
Owns the facilitator configuration, the smart router with auto-fallback
(including the EIP-7702 self-verify fallback for EVM chains), and the global
router instance accessors. Config constants (``X402_WALLET``,
``X402_TIMEOUT_SECONDS``, ``EIP7702_RPC``, …) are imported from the package
root; scheme helpers come from ``x402.scheme``.
Chain-specific verification and settlement helpers live in cohesive sibling
modules:
- ``facilitator_dispatch`` — per-network facilitator registration, pending
  authorizations and the chain-specific verify delegates (Solana / TRON /
  scaffolded non-EVM / EIP-7702).
- ``facilitator_settle`` — settlement receipt normalization + offline stub.
- ``facilitator_evm`` — EIP-7702 self-verify fallback (RPC key resolution,
  JSON-RPC calls, payTo/amount matching, settlement receipt).
- ``facilitator_solana_tron`` — Solana (SPL RPC) and TRON (TRC-20 Grid)
  on-chain verifiers plus the honest scaffolded fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.payments.x402 import (  # noqa: F401  (X402_* re-exported: tests monkeypatch them)
    X402_OFFLINE_MODE,
    X402_PLACEHOLDER_WALLETS,
    X402_SELF_FACILITATE,
    X402_SELF_FACILITATOR_KEY,
    X402_SELF_FACILITATOR_RPC,
    X402_TIMEOUT_SECONDS,
    X402_WALLET,
)
from pry.payments.x402.facilitator_config import (  # noqa: F401
    DEFAULT_FACILITATORS,
    FacilitatorConfig,
    NamedSigner,
    SignerRegistry,
)
from pry.payments.x402.facilitator_dispatch import DispatchMixin
from pry.payments.x402.facilitator_evm import (  # noqa: F401
    _CAIP2_TO_SHORT,
    ERC20_TRANSFER_SELECTOR,
    _eip7702_rpc_key,
    eip7702_matches,
    eip7702_settlement,
    eip7702_verify,
    rpc_call,
)
from pry.payments.x402.facilitator_health import FacilitatorHealthMixin
from pry.payments.x402.facilitator_self_hosted import SelfHostedMixin
from pry.payments.x402.facilitator_settle import SettleReceiptMixin
from pry.payments.x402.facilitator_solana_tron import (  # noqa: F401
    SCAFFOLDED_NETWORKS,
    _scaffold_non_evm_verify,
    verify_solana,
    verify_tron,
)
from pry.payments.x402.metrics import set_chain_active
from pry.payments.x402.scheme import (
    X402Scheme,
    asset_to_atomic,
    network_family,
    normalize_network_id,
    resolve_pay_to,
)
from pry.payments.x402.self_facilitator import SelfFacilitator  # noqa: TC001 — runtime type

if X402_OFFLINE_MODE:
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "x402_offline_mode_enabled",
        extra={"hint": "All payments auto-verify. NEVER use in production."},
    )

logger = logging.getLogger(__name__)


class FacilitatorRouter(DispatchMixin, SettleReceiptMixin, FacilitatorHealthMixin, SelfHostedMixin):
    """Smart router that picks the best facilitator per chain/asset.

    Falls back through enabled facilitators. Records failures and retries
    with exponential backoff. Supports EIP-7702 self-verify mode as a
    last-resort fallback for EVM chains.

    ``self_hosted`` mode (default off; opt-in via ``PRY_X402_SELF_FACILITATE=1``
    or the constructor arg) uses :class:`SelfFacilitator` INSTEAD of the
    external facilitator URLs — no Coinbase/CDP dependency. Custom per-network
    implementations can be plugged in via :meth:`register_facilitator`
    (the Solana/TRON extension point).
    """

    def __init__(
        self,
        facilitators: list[FacilitatorConfig] | None = None,
        self_hosted: bool | None = None,
    ) -> None:
        self.facilitators = sorted(
            [f for f in (facilitators or DEFAULT_FACILITATORS) if f.enabled and f.verify_url],
            key=lambda f: f.priority,
        )
        self._failures: dict[str, tuple[int, float]] = {}
        self._successes: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self.self_hosted = X402_SELF_FACILITATE if self_hosted is None else bool(self_hosted)
        self._self_facilitator: SelfFacilitator | None = None
        self._network_facilitators: dict[str, Any] = {}
        self._pending_auths: dict[str, dict[str, Any]] = {}
        self.signers = SignerRegistry()

    async def verify(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
        attested_required_atomic: int = 0,
    ) -> dict[str, Any]:
        """Verify a payment with the best available facilitator.

        Returns {"verified": bool, "reason": str, "settlement": dict|None}.

        ``attested_required_atomic`` (price binding, audit #7): when > 0, the
        attested challenge's SIGNED ``maxAmountRequired`` is passed through to
        the self-hosted verifier as the authoritative required amount for
        volatile-asset comparison (instead of a fresh live-oracle quote).
        Ignored by external facilitators.

        EVM chains are verified via configured facilitators, with an
        EIP-7702 self-verify fallback. Solana verifies on-chain via the SPL
        RPC verifier (``x402.solana_verifier``). TRON (SCAFFOLDED_NETWORKS)
        validates structure/price/asset and then reports "needs_facilitator"
        — it is never claimed verified without a real verifier. [REVIEW]
        """
        if X402_OFFLINE_MODE:
            return {"verified": True, "reason": "offline_mode", "settlement": None}

        network_id = normalize_network_id(network)
        if not network_id:
            set_chain_active(network, False)
            return {"verified": False, "reason": "unsupported network", "settlement": None}
        set_chain_active(network_id, True)

        if self.self_hosted or self._impl_for(network) is not None:
            return await self._verify_self_hosted(
                payment_id, tx_hash, network, asset, amount_usd, attested_required_atomic
            )

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": (resolve_pay_to(network) or ""),
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        healthy = [f for f in self.facilitators if self._is_healthy(f)]
        if not healthy:
            return {"verified": False, "reason": "no healthy facilitator", "settlement": None}

        facilitator = self._select_facilitator(healthy)
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            try:
                start_time = time.time()
                response: httpx.Response | None = None
                for attempt in range(3):
                    try:
                        response = await client.post(facilitator.verify_url, json=payload)
                        response.raise_for_status()
                        break
                    except (TimeoutError, httpx.HTTPError):
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (2**attempt))
                        else:
                            raise
                assert response is not None
                data = response.json()
                self._mark_success(facilitator, start_time=start_time)
                verified = bool(data.get("isValid") or data.get("verified") or data.get("success"))
                return {
                    "verified": verified,
                    "reason": data.get("error", data.get("reason", "")) if not verified else "",
                    "settlement": data if verified else None,
                    "facilitator": facilitator.name,
                }
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(e), "handler": "FacilitatorRouter.verify"},
                )
                last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                self._mark_failure(facilitator)
            except httpx.RequestError as e:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(e), "handler": "FacilitatorRouter.verify"},
                )
                last_error = f"{facilitator.name}: {e}"
                self._mark_failure(facilitator)
            except json.JSONDecodeError as e:
                logger.warning(
                    "payments_exception_swallowed",
                    extra={"error": str(e), "handler": "FacilitatorRouter.verify"},
                )
                last_error = f"{facilitator.name}: invalid JSON response - {e}"
                self._mark_failure(facilitator)

        if _eip7702_rpc_key(network) is not None:
            result = await self._eip7702_verify(tx_hash, network, asset, amount_usd)
            if result["verified"]:
                return result
            last_error = result.get("reason", last_error)

        if network_family(network) == "solana":
            return await self._verify_solana(payment_id, tx_hash, network, asset, amount_usd)
        if network_family(network) == "tron":
            return await self._verify_tron(payment_id, tx_hash, network, asset, amount_usd)

        return {"verified": False, "reason": last_error, "settlement": None}

    async def settle(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float,
    ) -> dict[str, Any]:
        """Confirm settlement with the best available facilitator."""
        if X402_OFFLINE_MODE:
            return self._offline_settlement(payment_id, tx_hash, network)

        network_id = normalize_network_id(network)
        if not network_id:
            set_chain_active(network, False)
            return {"success": False, "error": "unsupported network"}
        set_chain_active(network_id, True)

        if self.self_hosted or self._impl_for(network) is not None:
            return await self._settle_self_hosted(payment_id, tx_hash, network, asset, amount_usd)

        payload = {
            "paymentId": payment_id,
            "transactionHash": tx_hash,
            "network": network,
            "asset": asset,
            "amount": str(asset_to_atomic(amount_usd, asset, network)),
            "payToAddress": (resolve_pay_to(network) or ""),
            "scheme": X402Scheme.EXACT.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        last_error = "No facilitators available"
        healthy = [f for f in self.facilitators if self._is_healthy(f) and f.settle_url]
        facilitator = self._select_facilitator(healthy) if healthy else None
        async with httpx.AsyncClient(timeout=X402_TIMEOUT_SECONDS) as client:
            if facilitator is not None:
                try:
                    response = await client.post(facilitator.settle_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    self._mark_success(facilitator)
                    return self._normalize_settlement(
                        data, payment_id, tx_hash, network, facilitator.name
                    )
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        "payments_exception_swallowed",
                        extra={"error": str(e), "handler": "FacilitatorRouter.settle"},
                    )
                    last_error = f"{facilitator.name}: HTTP {e.response.status_code}"
                    self._mark_failure(facilitator)
                except httpx.RequestError as e:
                    logger.warning(
                        "payments_exception_swallowed",
                        extra={"error": str(e), "handler": "FacilitatorRouter.settle"},
                    )
                    last_error = f"{facilitator.name}: {e}"
                    self._mark_failure(facilitator)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "payments_exception_swallowed",
                        extra={"error": str(e), "handler": "FacilitatorRouter.settle"},
                    )
                    last_error = f"{facilitator.name}: invalid JSON response - {e}"
                    self._mark_failure(facilitator)

        if _eip7702_rpc_key(network) is not None:
            return self._eip7702_settlement(payment_id, tx_hash, network)

        if network_family(network) in ("solana", "tron"):
            return {
                "success": False,
                "payment_id": payment_id,
                "reason": "needs_facilitator: settlement verification not implemented "
                "for this chain",
                "scaffolded": True,
                "network": normalize_network_id(network),
            }

        return {
            "success": False,
            "payment_id": payment_id,
            "reason": last_error,
        }


_facilitator_router: FacilitatorRouter | None = None


def get_facilitator_router() -> FacilitatorRouter:
    """Return the global facilitator router."""
    global _facilitator_router
    if _facilitator_router is None:
        _facilitator_router = FacilitatorRouter()
    return _facilitator_router


def set_facilitator_router(router: FacilitatorRouter) -> None:
    """Override the global facilitator router (useful for tests)."""
    global _facilitator_router
    _facilitator_router = router


def register_facilitator(network: str, impl: Any) -> None:
    """Register a custom facilitator for ``network`` on the global router.

    Convenience wrapper over :meth:`FacilitatorRouter.register_facilitator`.
    Use this to plug in a custom verifier (e.g. TRON, which remains
    scaffolded until an impl is registered). ``impl`` must expose
    ``async verify(payment) -> VerifyResult`` and
    ``async settle(payment) -> str | None``.
    """
    get_facilitator_router().register_facilitator(network, impl)
