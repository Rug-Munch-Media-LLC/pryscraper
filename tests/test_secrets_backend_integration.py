# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Verify x402 and settings use secrets_backend.get_secret() for sensitive values."""

import os
from unittest.mock import patch


def test_settings_pulls_from_secrets_backend() -> None:
    """PrySettings should populate sensitive fields from secrets_backend.get_secret
    when env vars are not set."""

    # Force a known value from secrets_backend
    fake_secret = "fake-secret-from-gopass"  # noqa: S105

    def fake_get_secret(name: str, default: str = "") -> str:
        if name == "openrouter_api_key":
            return fake_secret
        return default

    # Clear env so the test is deterministic
    env = {k: v for k, v in os.environ.items() if not k.startswith("PRY_")}
    env["PRY_OPENROUTER_API_KEY"] = ""  # explicitly empty

    with (
        patch.dict(os.environ, env, clear=True),
        patch("secrets_backend.get_secret", side_effect=fake_get_secret),
    ):
        # Re-import fresh
        from settings import PrySettings

        s = PrySettings()
        # Sensitive field was empty in env, secrets_backend provided it
        assert s.openrouter_api_key == fake_secret, (
            f"Expected {fake_secret!r}, got {s.openrouter_api_key!r}"
        )


def test_x402_constants_come_from_secrets_backend() -> None:
    """x402.py X402_WALLET and X402_FACILITATOR_URL should be settable
    via secrets_backend.get_secret()."""
    fake_wallet = "0xABCDEF1234567890"
    fake_facilitator = "https://my-facilitator.example.com"

    def fake_get_secret(name: str, default: str = "") -> str:
        if name == "x402_wallet":
            return fake_wallet
        if name == "x402_facilitator":
            return fake_facilitator
        return default

    env = {k: v for k, v in os.environ.items() if not k.startswith("PRY_X402_")}

    with (
        patch.dict(os.environ, env, clear=True),
        patch("secrets_backend.get_secret", side_effect=fake_get_secret),
    ):
        # Force re-import of x402 constants
        import importlib

        import x402

        importlib.reload(x402)
        assert fake_wallet == x402.X402_WALLET
        assert fake_facilitator == x402.X402_FACILITATOR_URL


def test_settings_does_not_override_set_env() -> None:
    """If the env var is already set, secrets_backend must NOT override it."""
    fake_secret = "from-gopass"  # noqa: S105
    from_env = "from-env"

    def fake_get_secret(name: str, default: str = "") -> str:
        if name == "openrouter_api_key":
            return fake_secret
        return default

    env = {k: v for k, v in os.environ.items() if k != "PRY_OPENROUTER_API_KEY"}
    env["PRY_OPENROUTER_API_KEY"] = from_env

    with (
        patch.dict(os.environ, env, clear=True),
        patch("secrets_backend.get_secret", side_effect=fake_get_secret),
    ):
        from settings import PrySettings

        s = PrySettings()
        # Env wins over secrets_backend
        assert s.openrouter_api_key == from_env
