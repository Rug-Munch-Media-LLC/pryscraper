"""Pry — Camoufox SSRF route guard (compatibility re-export).

The implementation moved to :mod:`pry.engine.route_guard` so every browser
path shares one hop-validating guard. This module stays as the Camoufox-facing
import site used by ``camoufox_integration``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

from pry.engine.route_guard import guard_route, install_route_guard

__all__ = ["guard_route", "install_route_guard"]
