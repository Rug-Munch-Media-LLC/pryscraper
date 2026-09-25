from __future__ import annotations

from typing import Any

from pry.payments.x402.solana_constants import SUPPORTED_SOLANA_ASSETS
from pry.payments.x402.solana_result import _failure


def _validate_request(
    tx_signature: str,
    expected_recipient: str,
    amount_usd: float | None,
    asset: str | None,
) -> tuple[set[str] | None, str, dict[str, Any] | None]:
    """Validate request args before any RPC round-trip.

    Returns ``(allowed_assets, asset_upper, failure)`` — failure is None when
    the request is valid.
    """
    if not tx_signature:
        return None, "", _failure("missing tx signature")
    if not expected_recipient:
        return None, "", _failure("missing expected recipient")
    if amount_usd is None or amount_usd < 0:
        return None, "", _failure("invalid (negative) required amount")

    allowed_assets: set[str] | None = None
    asset_upper = ""
    if asset is not None:
        asset_upper = str(asset).strip().upper()
        if asset_upper not in SUPPORTED_SOLANA_ASSETS:
            return (
                None,
                "",
                _failure(
                    f"unsupported_asset: {asset!r} is not an advertised "
                    f"solana:mainnet asset ({', '.join(SUPPORTED_SOLANA_ASSETS)})"
                ),
            )
        allowed_assets = {asset_upper}
    return allowed_assets, asset_upper, None
