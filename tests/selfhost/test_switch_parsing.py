"""Kill-switch flag parsing: only an explicit falsy value turns a switch off.

Concern: the shared reader ``pry.api.kill_switches.is_enabled`` and its
agreement with the startup validator — pure in-process assertions, no app
assembly. What the switches DO to the assembled app lives in
``test_free_path.py``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import pytest


class TestSwitchParsing:
    """The flag parser: only an explicit falsy value turns a switch off."""

    def test_unset_means_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.delenv("PRY_TEST_SWITCH", raising=False)
        assert is_enabled("PRY_TEST_SWITCH", default=True) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " off "])
    def test_falsy_values_disable(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.setenv("PRY_TEST_SWITCH", value)
        assert is_enabled("PRY_TEST_SWITCH", default=True) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.setenv("PRY_TEST_SWITCH", value)
        assert is_enabled("PRY_TEST_SWITCH", default=False) is True

    def test_default_can_be_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pry.api.kill_switches import is_enabled

        monkeypatch.delenv("PRY_TEST_SWITCH", raising=False)
        assert is_enabled("PRY_TEST_SWITCH", default=False) is False

    @pytest.mark.parametrize(
        "value", ["1", "true", "TRUE", "yes", "on", "0", "false", "FALSE", "no", "off"]
    )
    def test_matches_the_startup_validator(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The app and config_validation must never disagree on a switch.

        They are separate readers of the same variables. A divergence would
        surface to an operator as "I switched x402 off and Pry still demands
        a payee wallet", which is indistinguishable from a broken toggle.

        The UNSET case differs by design and is pinned separately: the app
        reads a DEFAULT-ON switch (unset = subsystem installed), while the
        validator reads a REQUIREMENTS trigger (set-and-true = checks apply).
        Every explicit value must agree.
        """
        from pry.api.kill_switches import is_enabled
        from pry.core.config_validation import _env_flag

        monkeypatch.setenv("PRY_TEST_SHARED", value)
        assert is_enabled("PRY_TEST_SHARED", default=True) is _env_flag("PRY_TEST_SHARED"), (
            f"app and validator diverge on {value!r}"
        )
