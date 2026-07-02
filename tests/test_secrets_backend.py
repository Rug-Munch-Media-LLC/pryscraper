"""Tests for secrets_backend module."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import secrets_backend
from secrets_backend import (
    BACKEND_AUTO,
    BACKEND_ENV,
    BACKEND_FILE,
    BACKEND_GOPASS,
    _normalize_name,
    backend_info,
    get_secret,
    set_secret,
)


def test_normalize_name_adds_pry_prefix():
    assert _normalize_name("api_key") == "pry/api_key"
    assert _normalize_name("pry/api_key") == "pry/api_key"
    # Names that already have a slash are treated as paths (not re-prefixed)
    assert _normalize_name("PRY/api_key").startswith("pry/")


def test_get_secret_default_when_missing():
    # Use a name that definitely doesn't exist anywhere
    with patch.dict(os.environ, {"PRY_SECRET_BACKEND": "env"}, clear=False):
        # Clear any env vars that might match
        with patch.dict(os.environ, {}, clear=False):
            value = get_secret("definitely_not_a_real_secret_name_xyz_12345", default="missing")
    assert value == "missing"


def test_get_secret_from_env(monkeypatch):
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    monkeypatch.setenv("PRY_TEST_SECRET", "from-env")
    value = get_secret("test_secret")
    assert value == "from-env"


def test_get_secret_from_env_uppercase(monkeypatch):
    """Even when the caller passes lowercase, we should find PRY_UPPERCASE."""
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    monkeypatch.setenv("PRY_FOO", "upper-value")
    value = get_secret("foo")
    assert value == "upper-value"


def test_get_secret_falls_back_to_env_when_gopass_misses(monkeypatch):
    """When the active backend is gopass and a secret is not in gopass,
    we should fall back to the env (so partial migrations work)."""
    monkeypatch.setenv("PRY_SECRET_BACKEND", "gopass")
    monkeypatch.setenv("PRY_FALLBACK_TEST", "env-fallback")
    # gopass lookup will fail (entry doesn't exist), then we check env
    with patch("secrets_backend._get_from_gopass", return_value=None):
        value = get_secret("fallback_test")
    assert value == "env-fallback"


def test_backend_info_returns_expected_keys():
    info = backend_info()
    assert "requested" in info
    assert "active" in info
    assert "gopass_available" in info
    assert "gopass_path" in info
    assert "env_file" in info


def test_get_secret_from_file(tmp_path, monkeypatch):
    """Read a secret from a .env file when backend is file."""
    env_file = tmp_path / "test.env"
    env_file.write_text("PRY_FROM_FILE=hello\n# comment\nPRY_OTHER=world\n")
    monkeypatch.setenv("PRY_SECRET_BACKEND", "file")
    monkeypatch.setenv("PRY_ENV_FILE", str(env_file))
    # Reimport to pick up the new env file
    importlib.reload(secrets_backend)
    try:
        value = secrets_backend.get_secret("from_file")
        assert value == "hello"
    finally:
        # Restore
        monkeypatch.delenv("PRY_ENV_FILE", raising=False)
        importlib.reload(secrets_backend)


def test_set_secret_returns_false_when_gopass_unavailable(monkeypatch):
    monkeypatch.setattr(secrets_backend, "_GOPASS_AVAILABLE", False)
    # Force the global to be re-evaluated
    monkeypatch.setattr(secrets_backend, "_gopass_available", lambda: False)
    result = set_secret("test_secret", "value")
    assert result is False


def test_detect_backend_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("PRY_SECRET_BACKEND", "not-a-real-backend")
    backend = secrets_backend._detect_backend()
    assert backend == BACKEND_AUTO
