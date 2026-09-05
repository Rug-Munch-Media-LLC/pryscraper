"""x402 helper utilities (non-payment-logic)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations


def _check_secret_permissions() -> None:
    """Warn if secret files are world-readable."""
    import os
    import stat

    wallet_file = os.getenv("X402_WALLET_FILE", "")
    if wallet_file and os.path.exists(wallet_file):
        mode = os.stat(wallet_file).st_mode
        if mode & stat.S_IWGRP or mode & stat.S_IWOTH:
            import logging

            logging.getLogger(__name__).warning(
                "x402_secret_file_world_readable", extra={"file": wallet_file}
            )
