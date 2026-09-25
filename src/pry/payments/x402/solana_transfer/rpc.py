from __future__ import annotations

from typing import Any

import httpx

from pry.payments.x402.solana_constants import SOLANA_RPC_TIMEOUT_SECONDS
from pry.payments.x402.solana_result import _failure


async def _fetch_transaction(
    tx_signature: str, rpc_url: str
) -> tuple[dict[str, Any] | None, int, dict[str, Any] | None]:
    """Fetch and sanity-check ``getTransaction``.

    Returns ``(result, slot, failure)`` — result/slot are set only when
    failure is None.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_signature,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=SOLANA_RPC_TIMEOUT_SECONDS) as client:
            response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return None, 0, _failure(f"rpc_http_error: {e.response.status_code}")
    except httpx.RequestError as e:
        return None, 0, _failure(f"rpc_error: {e}")
    except ValueError as e:
        return None, 0, _failure(f"rpc_invalid_json: {e}")

    if not isinstance(data, dict):
        return None, 0, _failure("rpc_malformed_response")

    rpc_error = data.get("error")
    if rpc_error is not None:
        if isinstance(rpc_error, dict):
            code = rpc_error.get("code", "")
            message = rpc_error.get("message", "")
            return None, 0, _failure(f"rpc_error_response: {code} {message}".strip())
        return None, 0, _failure(f"rpc_error_response: {rpc_error}")

    result = data.get("result")
    if result is None:
        return None, 0, _failure("transaction_not_found")
    if not isinstance(result, dict):
        return None, 0, _failure("rpc_malformed_result")

    slot = result.get("slot")
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        return None, 0, _failure("rpc_malformed_meta")

    tx_err = meta.get("err")
    if tx_err is not None:
        return None, 0, _failure(f"transaction_failed: {tx_err}", slot=slot)

    if not isinstance(slot, int):
        # No slot means the RPC has not confirmed the tx into a block yet.
        return None, 0, _failure("transaction_not_confirmed")

    return result, slot, None
