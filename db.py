"""Pry - thin re-export facade for the ``db`` package.

The implementation now lives in the ``db/`` package (``session.py``,
``models.py``, ``import_json.py``, ``migrations.py``). A package shadows a
same-named module, so normal ``import db`` resolves to the package — this
file is kept so ALL existing ``from db import X`` imports keep working
unchanged, and so direct loads (e.g. ``python db.py``) expose the same API.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from db import *  # noqa: F403
