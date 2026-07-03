"""Pry API routers.

Each module in this package groups FastAPI endpoints by their `tags` field
(see api.py). The original api.py had 195 endpoints across 52 tags in a
single 4,668-line file. This package splits them so each router is
~50-300 lines (per CONVENTIONS.md, no file over 500 lines).

Pattern for each router file:

    from fastapi import APIRouter, Body, Query
    from typing import Any
    from errors import NotFoundError  # if needed

    router = APIRouter(tags=["Auth"])

    @router.post("/v1/auth/credentials", summary="...")
    async def store_credentials(...):
        ...

Then in api.py:
    from routers.auth import router as auth_router
    app.include_router(auth_router)

Migration order (one router at a time, each as a separate commit):
  1. auth        - done
  2. health      - easy (3 endpoints, no business logic)
  3. scraping    - core, but well-bounded
  4. extraction  - similar
  5. ... see docs/adr/0003-api-router-split.md for the full plan

The full split is a multi-hour refactor; this package is the
infrastructure for it. The first commit (this file + routers/auth.py)
demonstrates the pattern; subsequent commits can add more routers
without changing the overall structure.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

__all__: list[str] = [
    "auth_router",
    "health_router",
    "templates_router",
]
