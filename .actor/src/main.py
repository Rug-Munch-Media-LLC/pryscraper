"""Pry — Apify Actor entry point.

Thin wrapper around the SDK-aware entry in apify_actor.py. The Apify
platform invokes this file via Dockerfile.apify as
``python /usr/src/app/.actor/src/main.py``; we re-export ``main()``
so both the legacy ``python -m apify_actor`` invocation and the
standard .actor/src/main.py convention work.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# src-layout bootstrap: the real actor module lives at
# ``src/pry/actors/apify_actor.py`` (NOT the repo root). When the image runs
# ``python /usr/src/app/.actor/src/main.py``, Python only puts this script's
# directory (``.actor/src``) on ``sys.path`` — so neither ``pry`` (the package)
# nor a bare ``apify_actor`` module would resolve. Add the ``src`` root so
# ``pry.actors`` works both in the container and from a source checkout.
_APP_ROOT = Path(__file__).resolve().parents[2]
_SRC = _APP_ROOT / "src"
for _path in (_SRC, _APP_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from pry.actors.apify_actor import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
