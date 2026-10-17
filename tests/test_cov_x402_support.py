"""Shared fakes for the x402 settle branch tests."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import threading

from pry.payments.x402 import handler_settle as hs


class Usage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, str]] = []

    def record(self, payment_id: str, *, amount_usd: float, network: str) -> None:
        self.calls.append((payment_id, amount_usd, network))


class Router:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls: list[dict] = []

    async def settle(self, **kwargs):
        self.calls.append(kwargs)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class SettleHost(hs.SettleMixin):
    def __init__(self, router: Router, use_db: bool = False) -> None:
        self.router = router
        self._settled_txs: dict[str, dict] = {}
        self._use_db = use_db
        self._verify_lock = threading.Lock()
        self._pre_settle_hooks: list = []
        self._post_settle_hooks: list = []
        self.records: list[dict] = []
        self.usage = Usage()

    def _settlement_key(self, payment: dict) -> str:
        return f"{payment['network']}:{payment['tx_hash']}"

    def _record_settlement(self, record: dict) -> None:
        self.records.append(record)


def ok_receipt() -> dict:
    return {"success": True, "reason": "", "transaction": "0xfeed"}


class Resp:
    def __init__(self, value: str) -> None:
        self.headers = {"Retry-After": value}


class Exc(Exception):
    def __init__(self, value: str | None = None) -> None:
        super().__init__("x")
        self.response = Resp(value) if value is not None else None
