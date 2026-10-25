"""``python -m pry.actors.apify_actor`` entry point."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio

from pry.actors.apify_actor.runner import main

if __name__ == "__main__":
    asyncio.run(main())
