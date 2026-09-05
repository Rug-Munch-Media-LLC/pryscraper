"""Pry — x402 facilitator configuration.

Extracted from ``facilitator.py``: the signer registry, per-facilitator
config dataclass, and the default facilitator list (env-overridable).
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pry.payments.x402 import X402_TIMEOUT_SECONDS


@dataclass
class NamedSigner:
    name: str
    source: str  # "env" or "file"
    env_var: str = ""
    file_path: str = ""
    encoding: str = "hex"  # hex, base58, utf8, base64


class SignerRegistry:
    """Named signer registry with per-network references."""

    def __init__(self) -> None:
        self._signers: dict[str, NamedSigner] = {}
        self._network_signers: dict[str, list[str]] = {}

    def register(
        self,
        name: str,
        source: str = "env",
        env_var: str = "",
        file_path: str = "",
        encoding: str = "hex",
    ) -> None:
        self._signers[name] = NamedSigner(name, source, env_var, file_path, encoding)

    def assign(self, network: str, signer_names: list[str]) -> None:
        self._network_signers[network] = signer_names

    def get_signers(self, network: str) -> list[NamedSigner]:
        names = self._network_signers.get(network, [])
        return [self._signers[n] for n in names if n in self._signers]

    def resolve_key(self, name: str) -> str:
        s = self._signers.get(name)
        if not s:
            return ""
        if s.source == "env":
            return os.getenv(s.env_var, "")
        if s.source == "file" and s.file_path:
            try:
                with open(s.file_path) as f:
                    return f.read().strip()
            except OSError:
                return ""
        return ""


@dataclass
class FacilitatorConfig:
    """Configuration for a single x402 facilitator."""

    name: str
    verify_url: str
    settle_url: str
    priority: int = 0
    enabled: bool = True
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = X402_TIMEOUT_SECONDS


# Default facilitator router — override via env or runtime config.
DEFAULT_FACILITATORS: list[FacilitatorConfig] = [
    FacilitatorConfig(
        name="coinbase",
        verify_url=os.getenv("PRY_X402_COINBASE_VERIFY", "https://x402.org/facilitator/verify"),
        settle_url=os.getenv("PRY_X402_COINBASE_SETTLE", "https://x402.org/facilitator/settle"),
        priority=int(os.getenv("PRY_X402_COINBASE_PRIORITY", "1")),
        enabled=os.getenv("PRY_X402_COINBASE_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="payai",
        verify_url=os.getenv("PRY_X402_PAYAI_VERIFY", "https://facilitator.payai.network/verify"),
        settle_url=os.getenv("PRY_X402_PAYAI_SETTLE", "https://facilitator.payai.network/settle"),
        priority=int(os.getenv("PRY_X402_PAYAI_PRIORITY", "2")),
        enabled=os.getenv("PRY_X402_PAYAI_ENABLED", "true").lower() in ("1", "true"),
    ),
    FacilitatorConfig(
        name="cloudflare",
        verify_url=os.getenv("PRY_X402_CF_VERIFY", ""),
        settle_url=os.getenv("PRY_X402_CF_SETTLE", ""),
        priority=int(os.getenv("PRY_X402_CF_PRIORITY", "3")),
        enabled=os.getenv("PRY_X402_CF_ENABLED", "false").lower() in ("1", "true"),
    ),
]
