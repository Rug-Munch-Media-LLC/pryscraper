"""Config validation agrees with the app on the x402 switch.

Concern: the BOOT-TIME validator — if it and the assembled app read the same
variable differently, an operator could switch x402 off, still be told the
instance needs a payee wallet at boot, and conclude the switch is broken.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from types import SimpleNamespace
from typing import Any

import pytest


def _settings() -> Any:
    """A minimal settings stub: the validator reads only these fields."""
    return SimpleNamespace(
        host="127.0.0.1",
        port=8002,
        api_key="selfhost-stub",
        database_url="",
        redis_url="",
        proxy_url="",
        proxy_enabled=False,
        x402_wallet="",
        rate_limit_rpm=120,
    )


class TestConfigValidationAgrees:
    """The validator and the app must read the same switch."""

    def test_no_wallet_required_when_x402_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.core.config_validation import has_errors, validate_config

        monkeypatch.setenv("PRY_X402_ENABLED", "false")
        monkeypatch.setenv("PRY_X402_WALLET", "")
        issues = validate_config(_settings())
        assert not any("x402 is enabled" in issue for issue in issues), issues
        assert not has_errors(issues), issues

    def test_wallet_required_when_x402_is_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.core.config_validation import validate_config

        monkeypatch.setenv("PRY_X402_ENABLED", "true")
        monkeypatch.setenv("PRY_X402_WALLET", "")
        issues = validate_config(_settings())
        assert any("x402 is enabled" in issue for issue in issues), issues
