"""Tests for the logging_config module."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging

import pytest

import logging_config


@pytest.fixture(autouse=True)
def _reset_logging_state(monkeypatch):
    """Force re-configuration for each test by clearing the module flag and
    detaching the handlers we set up."""
    logging_config._configured = False
    # Also clear root handlers to avoid leaking between tests
    logging.getLogger().handlers = []
    yield
    logging_config._configured = False
    logging.getLogger().handlers = []


def test_setup_logging_is_idempotent():
    logging_config.setup_logging()
    assert logging_config.is_configured() is True
    h1 = list(logging.getLogger().handlers)
    logging_config.setup_logging()  # second call should be a no-op
    h2 = list(logging.getLogger().handlers)
    assert h1 == h2


def test_json_output_has_required_fields(capsys):
    logging_config.setup_logging()
    log = logging_config.get_logger("test_module")
    log.info("test_event", key="value", count=42)
    captured = capsys.readouterr()
    # Find the JSON line
    lines = [line for line in captured.out.splitlines() if line.strip().startswith("{")]
    assert lines, f"no JSON output: {captured.out!r}"
    record = json.loads(lines[0])
    # Per CONVENTIONS.md Part 5, required fields: timestamp, level, service, event
    assert "timestamp" in record
    assert "level" in record
    assert "service" in record
    assert record["service"] == "pry"
    assert record["event"] == "test_event"
    assert record["key"] == "value"
    assert record["count"] == 42


def test_console_output_is_not_json(capsys, monkeypatch):
    monkeypatch.setenv("PRY_LOG_FORMAT", "console")
    logging_config.setup_logging()
    log = logging_config.get_logger("test_module")
    log.info("test_event", key="value")
    captured = capsys.readouterr()
    # Should contain "test_event" but not be valid JSON
    assert "test_event" in captured.out
    # First line should NOT be a JSON dict
    first_line = captured.out.splitlines()[0]
    with pytest.raises(json.JSONDecodeError):
        json.loads(first_line)


def test_log_level_override():
    logging_config.setup_logging(level=logging.WARNING)
    assert logging.getLogger().level == logging.WARNING


def test_get_logger_returns_logger():
    log = logging_config.get_logger("test_mod")
    # Should have either a structlog API (info method that takes kwargs)
    # or a stdlib Logger (info method that takes msg + args)
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")
    assert callable(log.info)


def test_setup_logging_without_structlog_falls_back(monkeypatch):
    """If structlog isn't available, setup_logging should still work."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "structlog" or name.startswith("structlog."):
            raise ImportError("simulated missing structlog")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Force a fresh import
    import importlib

    importlib.reload(logging_config)
    try:
        logging_config.setup_logging()
        # basicConfig should have been called
        assert logging.getLogger().handlers
    finally:
        # Restore structlog
        importlib.reload(logging_config)


def test_default_level_is_info(monkeypatch):
    monkeypatch.delenv("PRY_LOG_LEVEL", raising=False)
    assert logging_config._resolve_level() == logging.INFO


def test_resolve_level_handles_bad_input(monkeypatch):
    monkeypatch.setenv("PRY_LOG_LEVEL", "not-a-real-level")
    assert logging_config._resolve_level() == logging.INFO
