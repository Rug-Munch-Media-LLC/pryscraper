# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Production guard for x402 offline mode (quality audit #4).

PRY_DATABASE_URL is the production indicator (dev defaults to embedded
SQLite). If X402_OFFLINE_MODE is somehow active while a database is
configured, the package auto-disables it and logs CRITICAL — a stale
DEBUG=true in production must never auto-verify all payments.

Escape hatch: PRY_X402_OFFLINE_FORCE=true keeps offline mode on (for
testing against a configured DB) but still logs a warning.
"""

from __future__ import annotations

import importlib
import logging

import pytest

import pry.payments.x402 as x402


@pytest.fixture
def reload_x402(monkeypatch: pytest.MonkeyPatch):
    """Reload the x402 package with a controlled env and restore after."""

    def _reload(**env: str) -> object:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(x402)

    yield _reload
    importlib.reload(x402)


def test_offline_mode_without_db_url_works_dev(reload_x402, caplog) -> None:
    """Offline mode with no PRY_DATABASE_URL → stays enabled (dev)."""
    mod = reload_x402(
        PRY_DEBUG="true",
        PRY_X402_OFFLINE="true",
        PRY_DATABASE_URL="",
    )
    assert mod.X402_OFFLINE_MODE is True
    assert mod.X402_OFFLINE_FORCE is False
    # No production auto-disable message.
    assert not any(
        "auto-disabled" in r.message for r in caplog.records if r.levelno >= logging.WARNING
    )


def test_offline_mode_with_db_url_auto_disabled(reload_x402, caplog) -> None:
    """Offline mode + PRY_DATABASE_URL → auto-disabled with CRITICAL log."""
    with caplog.at_level(logging.CRITICAL, logger="pry.payments.x402"):
        mod = reload_x402(
            PRY_DEBUG="true",
            PRY_X402_OFFLINE="true",
            PRY_DATABASE_URL="postgresql://prod-db.example/pry",
        )
    assert mod.X402_OFFLINE_MODE is False
    assert any(
        r.levelno == logging.CRITICAL
        and "X402_OFFLINE_MODE auto-disabled in production (PRY_DATABASE_URL is set)" in r.message
        for r in caplog.records
    )


def test_offline_mode_with_db_url_force_keeps_enabled(reload_x402, caplog) -> None:
    """FORCE=true overrides the guard but still logs a warning."""
    with caplog.at_level(logging.WARNING, logger="pry.payments.x402"):
        mod = reload_x402(
            PRY_DEBUG="true",
            PRY_X402_OFFLINE="true",
            PRY_X402_OFFLINE_FORCE="true",
            PRY_DATABASE_URL="postgresql://prod-db.example/pry",
        )
    assert mod.X402_OFFLINE_MODE is True
    assert mod.X402_OFFLINE_FORCE is True
    assert any(
        r.levelno == logging.WARNING
        and "forced ON in production" in r.message
        and "PRY_X402_OFFLINE_FORCE" in r.message
        for r in caplog.records
    )
    # The auto-disable CRITICAL must NOT fire when forced.
    assert not any(
        r.levelno == logging.CRITICAL and "auto-disabled" in r.message for r in caplog.records
    )
