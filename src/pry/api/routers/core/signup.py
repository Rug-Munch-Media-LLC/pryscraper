"""Pry — Signup automation router.

Exposes ``POST /v1/signup`` — register an account on a target site using the
:class:`~signup.engine.SignupAutomation` engine.

NOTE FOR THE LEAD: this router is intentionally NOT wired into ``api.py``.
To enable the endpoint, add the following two lines to ``api.py`` (next to the
other ``routers.*`` imports / includes):

    from pry.api.routers.core.signup import router as signup_router
    ...
    app.include_router(signup_router)

The module is import-safe on its own: ``import pry.api.routers.signup`` works whether
or not it is wired, and the engine import happens lazily inside the handler.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Signup"])


class SignupRequest(BaseModel):
    """Request body for :func:`signup`."""

    url: str = Field(..., description="URL of the signup/registration page")
    email: str = Field(..., description="Email address to register with")
    profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra profile values keyed by field role or field name "
        '(e.g. {"full_name": "Jane Doe", "username": "jane"})',
    )


@router.post(
    "/v1/signup",
    summary="Automatically register an account",
    description=(
        "Fetches the signup page, detects the registration form, fills it with "
        "the provided profile + a generated password, submits, and optionally "
        "verifies the email. Returns status, session cookies, the generated "
        "password and verification info. Results are in-memory only."
    ),
)
async def signup(request: SignupRequest) -> dict[str, Any]:
    """Register an account at ``request.url`` and return the outcome."""
    from pry.commerce.signup.engine import SignupAutomation

    engine = SignupAutomation()
    try:
        return await engine.register(request.url, request.profile, request.email)
    finally:
        await engine.close()
