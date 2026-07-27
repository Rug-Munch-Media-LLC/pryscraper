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

from apify_actor import main

if __name__ == "__main__":
    asyncio.run(main())
