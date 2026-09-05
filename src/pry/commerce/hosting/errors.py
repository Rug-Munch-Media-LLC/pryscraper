# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Exception hierarchy for the hosting signup / checkout flow."""

from __future__ import annotations


class HostingError(Exception):
    """Base class for hosting signup errors."""


class PlanNotFound(HostingError):
    """Raised for an unknown plan tier."""


class PlanNotPurchasable(HostingError):
    """Raised when a plan has no fixed monthly price (enterprise custom quote)."""


class WalletUnconfigured(HostingError):
    """Fail-closed: no real receiving wallet is configured for the network."""


class InstanceNotFound(HostingError):
    """Raised for an unknown hosted instance id."""


class Underpayment(HostingError):
    """Raised when a reported tx does not verify — never credited/provisioned."""

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason
