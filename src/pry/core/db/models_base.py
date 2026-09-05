"""Pry - SQLAlchemy base: DeclarativeBase, _now helper, _HAS_SA flag.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# pyright: basic
from __future__ import annotations

from datetime import UTC, datetime

try:
    from sqlalchemy.orm import DeclarativeBase

    _HAS_SA = True
except ImportError:  # pragma: no cover
    _HAS_SA = False

if _HAS_SA:

    class Base(DeclarativeBase):
        pass

    def _now() -> datetime:
        return datetime.now(UTC)

else:  # pragma: no cover
    Base = None  # type: ignore
