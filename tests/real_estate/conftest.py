# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Fixtures for the real-estate router tests.

The split of the monolithic real-estate module left ``real_estate_app`` in
``_real_estate_support2.py``.  pytest only collects fixtures from ``conftest.py``
(and from modules a conftest imports), so the fixture is re-exported here instead
of being duplicated.
"""

from __future__ import annotations

from ._real_estate_support2 import real_estate_app

__all__ = ["real_estate_app"]
