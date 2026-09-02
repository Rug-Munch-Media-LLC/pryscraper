"""Pry — shared httpx client pool (re-exported from pry.core.client).

All modules import ``get_client`` instead of creating new clients per request.
The implementation lives in ``pry.core.client`` to keep the core layer pure
(no engine→api dependency for import-linter).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry.core.client import (
    close_client,
    get_client,
    http_client,
)

__all__ = ["close_client", "get_client", "http_client"]
