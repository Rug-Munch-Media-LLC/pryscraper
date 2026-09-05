"""Pry — JSON-RPC transport + tx broadcast for the EVM self-facilitator."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

import httpx

from .evm_common import _DEFAULT_TX_GAS


class EVMRpcMixin:
    """RPC client helpers and raw-tx broadcast for :class:`SelfFacilitator`."""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)

    async def _rpc_call(self, client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
        """Issue a JSON-RPC call against ``self.rpc_url``; returns result or None."""
        if not self.rpc_url:
            return None
        response = await client.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise ValueError(f"RPC error {method}: {data['error']}")
        return data.get("result") if isinstance(data, dict) else None

    async def _send_tx(
        self,
        client: httpx.AsyncClient,
        *,
        to: str,
        data: str,
        chain_id: int,
        value: int,
    ) -> str | None:
        """Fetch nonce/gas, sign a legacy tx, broadcast, return tx hash."""
        assert self._acct is not None
        payer = self._signer.public_key.to_checksum_address() if self._signer else ""
        nonce_hex = await self._rpc_call(client, "eth_getTransactionCount", [payer, "pending"])
        if nonce_hex is None:
            return None
        nonce = int(str(nonce_hex), 16)

        gas_limit = _DEFAULT_TX_GAS
        try:
            estimated = await self._rpc_call(
                client,
                "eth_estimateGas",
                [{"from": payer, "to": to, "data": data, "value": hex(value)}],
            )
            if estimated is not None:
                gas_limit = int(str(estimated), 16)
        except (ValueError, httpx.HTTPError):
            pass

        gas_price_hex = await self._rpc_call(client, "eth_gasPrice", [])
        if gas_price_hex is None:
            return None
        gas_price = int(str(gas_price_hex), 16)

        signed = self._acct.sign_transaction(
            {
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": gas_limit,
                "to": to,
                "value": value,
                "data": data,
                "chainId": chain_id,
            }
        )
        raw = str(signed.raw_transaction.hex())
        result = await self._rpc_call(
            client, "eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")]
        )
        return str(result) if result else None
