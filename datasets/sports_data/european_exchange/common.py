"""Shared runtime hooks for European exchange fetchers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
try:
    from datasets.sports_data.odds import _event_label
except ImportError:  # pragma: no cover - parallel build guard
    _event_label = None  # type: ignore[assignment]
