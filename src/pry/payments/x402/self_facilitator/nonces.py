"""Pry — bounded replay-protection nonce store for the self-facilitator."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


class NonceStore:
    """Bounded set of used EIP-3009 nonces with optional JSON persistence.

    Replay protection is keyed by ``chain_id:token:nonce`` (a nonce is only
    unique per token contract). The store is bounded (oldest entries are
    evicted past ``max_size``) and persisted to ``path`` as JSON so used
    nonces survive restarts.
    """

    def __init__(self, path: Path | str | None = None, max_size: int = 10_000) -> None:
        self._path = Path(path) if path else None
        self._max_size = max(int(max_size), 1)
        self._used: set[str] = set()
        self._order: deque[str] = deque()
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "NonceStore._load"},
            )
            return
        nonces = data.get("nonces") if isinstance(data, dict) else data
        if not isinstance(nonces, list):
            return
        for nonce in nonces:
            if isinstance(nonce, str) and nonce not in self._used:
                self._used.add(nonce)
                self._order.append(nonce)
                self._trim()

    def contains(self, nonce_key: str) -> bool:
        return nonce_key in self._used

    def mark_used(self, nonce_key: str) -> bool:
        """Record a used nonce key. Returns False when it was already used."""
        if nonce_key in self._used:
            return False
        self._used.add(nonce_key)
        self._order.append(nonce_key)
        self._trim()
        self._persist()
        return True

    def _trim(self) -> None:
        while len(self._order) > self._max_size:
            oldest = self._order.popleft()
            self._used.discard(oldest)

    def _persist(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"nonces": sorted(self._used), "max_size": self._max_size},
                    sort_keys=True,
                )
            )
        except OSError as e:
            logger.warning("x402_nonce_persist_failed", extra={"error": str(e)})

    def clear(self) -> None:
        self._used.clear()
        self._order.clear()

    @property
    def count(self) -> int:
        return len(self._used)
