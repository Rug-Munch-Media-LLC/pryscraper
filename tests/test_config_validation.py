"""Tests for config_validation.validate_config.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pry.core import config_validation
from pry.core.config_validation import (
    ERROR_PREFIX,
    WARNING_PREFIX,
    has_errors,
    is_loopback_host,
    validate_config,
    validate_config_strict,
)


def make_settings(**overrides: object) -> SimpleNamespace:
    """Return a minimal duck-typed settings object with sane defaults."""
    defaults: dict[str, object] = {
        "host": "127.0.0.1",
        "api_key": "test-key",
        "rate_limit_rpm": 120,
        "proxy_url": "",
        "proxy_enabled": False,
        "database_url": "sqlite:///data/pry.db",
        "redis_url": "redis://localhost:6379/0",
        "port": 8002,
        "max_chars": 100000,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_valid_config_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRY_X402_ENABLED", raising=False)
    monkeypatch.delenv("PRY_X402_WALLET", raising=False)
    assert validate_config(make_settings()) == []


def test_missing_api_key_on_loopback_is_warning() -> None:
    issues = validate_config(make_settings(api_key=""))
    assert issues  # at least the loopback warning
    assert not has_errors(issues)
    assert any("PRY_API_KEY is empty" in i for i in issues)


def test_missing_api_key_on_non_loopback_is_error() -> None:
    issues = validate_config(make_settings(host="0.0.0.0", api_key=""))  # noqa: S104
    assert has_errors(issues)
    assert any(i.startswith(ERROR_PREFIX) and "non-loopback host '0.0.0.0'" in i for i in issues)


def test_bind_to_private_ip_without_key_is_error() -> None:
    issues = validate_config(make_settings(host="10.0.0.5", api_key=""))
    assert has_errors(issues)


def test_invalid_rate_limit_non_int_is_error() -> None:
    issues = validate_config(make_settings(rate_limit_rpm="banana"))
    assert has_errors(issues)
    assert any("must be an integer" in i for i in issues)


def test_invalid_rate_limit_zero_is_error() -> None:
    issues = validate_config(make_settings(rate_limit_rpm=0))
    assert has_errors(issues)


def test_invalid_rate_limit_negative_is_error() -> None:
    issues = validate_config(make_settings(rate_limit_rpm=-5))
    assert has_errors(issues)


def test_rate_limit_absurd_high_is_error() -> None:
    issues = validate_config(make_settings(rate_limit_rpm=1_000_000))
    assert has_errors(issues)


def test_rate_limit_high_is_warning() -> None:
    issues = validate_config(make_settings(rate_limit_rpm=10_000))
    assert not has_errors(issues)
    assert any("very high" in i for i in issues)


def test_proxy_url_without_scheme_is_error() -> None:
    issues = validate_config(make_settings(proxy_url="proxy.example:8080", proxy_enabled=True))
    assert has_errors(issues)
    assert any("has no scheme" in i for i in issues)


def test_proxy_url_bad_scheme_is_error() -> None:
    issues = validate_config(make_settings(proxy_url="ftp://proxy.example:21", proxy_enabled=True))
    assert has_errors(issues)
    assert any("not supported" in i for i in issues)


def test_proxy_url_valid_socks5_is_ok() -> None:
    issues = validate_config(
        make_settings(proxy_url="socks5://user:pass@host:1080", proxy_enabled=True)
    )
    assert not has_errors(issues)


def test_proxy_url_set_but_disabled_is_warning() -> None:
    issues = validate_config(make_settings(proxy_url="http://proxy:8080", proxy_enabled=False))
    assert not has_errors(issues)
    assert any("will be ignored" in i for i in issues)


def test_proxy_enabled_without_url_is_warning() -> None:
    issues = validate_config(make_settings(proxy_url="", proxy_enabled=True))
    assert not has_errors(issues)
    assert any("no proxy URL" in i for i in issues)


def test_x402_enabled_without_wallet_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_X402_ENABLED", "true")
    monkeypatch.delenv("PRY_X402_WALLET", raising=False)
    issues = validate_config(make_settings())
    assert has_errors(issues)
    assert any("x402 is enabled but no wallet" in i for i in issues)


def test_x402_enabled_with_placeholder_wallet_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_X402_ENABLED", "true")
    monkeypatch.setenv("PRY_X402_WALLET", "pry-default-wallet")
    issues = validate_config(make_settings())
    assert has_errors(issues)


def test_x402_enabled_with_wallet_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_X402_ENABLED", "true")
    monkeypatch.setenv("PRY_X402_WALLET", "0xabc123")
    issues = validate_config(make_settings())
    assert not has_errors(issues)


def test_x402_settings_attributes_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_X402_ENABLED", "false")
    issues = validate_config(make_settings(x402_enabled=True, x402_wallet="0xfrom-settings"))
    assert not has_errors(issues)


def test_x402_bad_facilitator_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_X402_ENABLED", "true")
    monkeypatch.setenv("PRY_X402_WALLET", "0xabc123")
    monkeypatch.setenv("PRY_X402_FACILITATOR", "not-a-url")
    issues = validate_config(make_settings())
    assert has_errors(issues)
    assert any("facilitator URL" in i for i in issues)


def test_bad_database_scheme_is_warning() -> None:
    issues = validate_config(make_settings(database_url="mongodb://localhost/pry"))
    assert not has_errors(issues)
    assert any("PRY_DATABASE_URL scheme" in i for i in issues)


def test_bad_redis_scheme_is_warning() -> None:
    issues = validate_config(make_settings(redis_url="http://localhost:6379"))
    assert not has_errors(issues)
    assert any("PRY_REDIS_URL scheme" in i for i in issues)


def test_bad_port_is_error() -> None:
    issues = validate_config(make_settings(port=99999))
    assert has_errors(issues)
    assert any("PRY_PORT" in i for i in issues)


def test_non_positive_max_chars_is_error() -> None:
    issues = validate_config(make_settings(max_chars=0))
    assert has_errors(issues)
    assert any("PRY_MAX_CHARS" in i for i in issues)


def test_has_errors_and_errors_only() -> None:
    assert has_errors([f"{ERROR_PREFIX} boom"]) is True
    assert has_errors([f"{WARNING_PREFIX} meh"]) is False
    assert has_errors([]) is False
    expected = [f"{ERROR_PREFIX} a"]
    assert config_validation.errors_only([f"{ERROR_PREFIX} a", f"{WARNING_PREFIX} b"]) == expected


def test_validate_config_strict_raises_on_error() -> None:
    with pytest.raises(ValueError, match="PRY_API_KEY is empty"):
        validate_config_strict(make_settings(host="0.0.0.0", api_key=""))  # noqa: S104


def test_validate_config_strict_allows_warnings() -> None:
    issues = validate_config_strict(make_settings(api_key=""))
    assert isinstance(issues, list)
    assert not has_errors(issues)


def test_is_loopback_host() -> None:
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("::1") is True
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("127.9.9.9") is True  # whole 127/8 range
    assert is_loopback_host("0.0.0.0") is False  # noqa: S104
    assert is_loopback_host("10.0.0.1") is False
    assert is_loopback_host("") is False
