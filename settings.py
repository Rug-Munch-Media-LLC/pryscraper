"""Pry — centralized settings via Pydantic BaseSettings.

Every environment variable lives here. Import the `settings` singleton
everywhere else.

Legacy env vars without the `PRY_` prefix (e.g. `PROXY_URL`, `TOR_ENABLED`)
are still accepted during a deprecation window.

The settings object also loads and persists runtime overrides from a JSON
config file (default `/app/config.json`).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_FILE = Path("/app/config.json")

# Map legacy nested config keys (from the old mconfig JSON file and API)
# to flat attribute names on PrySettings.
_NESTED_KEY_MAP: dict[str, str] = {
    "proxy.enabled": "proxy_enabled",
    "proxy.type": "proxy_type",
    "proxy.url": "proxy_url",
    "proxy.username": "proxy_username",
    "proxy.password": "proxy_password",
    "tor.enabled": "tor_enabled",
    "tor.socks5_host": "tor_socks5_host",
    "tor.socks5_port": "tor_socks5_port",
    "tor.control_port": "tor_control_port",
    "rotation.user_agent": "rotation_user_agent",
    "rotation.ip": "ip_rotation",
    "rotation.timing": "rotation_timing",
    "rotation.delay_range": "rotation_delay_range",
    "stealth.webdriver_override": "webdriver_override",
    "stealth.canvas_noise": "canvas_noise",
    "stealth.webrtc_disable": "webrtc_disable",
    "stealth.geolocation_spoof": "geolocation_spoof",
    "retry.max_attempts": "max_retries",
    "retry.min_quality": "min_quality",
    "retry.backoff": "retry_backoff",
    "output.default_format": "default_format",
    "output.max_chars": "max_chars",
    "output.include_links": "include_links",
    "rate_limit.rpm": "rate_limit_rpm",
}


class PrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Core
    app_name: str = "Pry"
    app_version: str = "3.0.0"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8002
    url: str = "http://localhost:8002"
    api_key: str = ""

    # Database / cache
    database_url: str = "postgresql+asyncpg://pry:pry@localhost/pry"
    redis_url: str = "redis://localhost:6379/0"

    # LLM providers
    ollama_url: str = "http://localhost:11434"
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""

    # Services
    flaresolverr_url: str = "http://flaresolverr:8191/v1"
    webhook_secret: str = "pry-webhook-secret"

    # Proxy (legacy env aliases for migration)
    proxy_url: str = Field(
        default="",
        validation_alias=AliasChoices("PRY_PROXY_URL", "PROXY_URL"),
    )
    proxy_type: str = Field(
        default="http",
        validation_alias=AliasChoices("PRY_PROXY_TYPE", "PROXY_TYPE"),
    )
    proxy_username: str = Field(
        default="",
        validation_alias=AliasChoices("PRY_PROXY_USERNAME", "PROXY_USERNAME"),
    )
    proxy_password: str = Field(
        default="",
        validation_alias=AliasChoices("PRY_PROXY_PASSWORD", "PROXY_PASSWORD"),
    )
    proxy_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("PRY_PROXY_ENABLED", "PROXY_ENABLED"),
    )

    # Tor (legacy env aliases)
    tor_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("PRY_TOR_ENABLED", "TOR_ENABLED"),
    )
    tor_socks5_host: str = Field(
        default="tor",
        validation_alias=AliasChoices("PRY_TOR_SOCKS5_HOST", "TOR_SOCKS5_HOST"),
    )
    tor_socks5_port: int = Field(
        default=9050,
        validation_alias=AliasChoices("PRY_TOR_SOCKS5_PORT", "TOR_SOCKS5_PORT"),
    )
    tor_control_port: int = 9051

    # Rotation / retry (legacy env aliases)
    rotation_user_agent: str = "rotate"
    ip_rotation: str = Field(
        default="off",
        validation_alias=AliasChoices("PRY_IP_ROTATION", "IP_ROTATION"),
    )
    rotation_timing: str = "random"
    rotation_delay_range: tuple[float, float] = (0.5, 3.0)
    max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("PRY_MAX_RETRIES", "MAX_RETRIES"),
    )
    min_quality: int = Field(
        default=20,
        validation_alias=AliasChoices("PRY_MIN_QUALITY", "MIN_QUALITY"),
    )
    retry_backoff: str = "exponential"
    rate_limit_rpm: int = Field(
        default=120,
        validation_alias=AliasChoices("PRY_RATE_LIMIT_RPM", "RATE_LIMIT_RPM"),
    )

    # Stealth
    stealth_enabled: bool = True
    random_user_agent: bool = True
    webdriver_override: bool = True
    canvas_noise: bool = True
    webrtc_disable: bool = True
    geolocation_spoof: bool = True
    min_delay_ms: int = 500
    max_delay_ms: int = 3000

    # Output
    default_format: str = "markdown"
    max_chars: int = 100000
    include_links: bool = True

    # Storage
    screenshot_dir: Path = Path("/tmp/pry-screenshots")  # nosec B108
    cache_ttl_seconds: int = 3600
    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        validation_alias=AliasChoices("PRY_CONFIG_FILE", "CONFIG_FILE"),
    )

    # x402 / MCP
    x402_enabled: bool = False
    x402_pay_to: str = ""
    mcp_enabled: bool = True
    mcp_tools_count: int = 8

    # Rate limits (legacy Settings class)
    rate_limit_per_domain: int = 10
    rate_limit_per_ip: int = 60

    def model_post_init(self, __context: Any) -> None:
        """Load runtime overrides from the JSON config file after env parsing."""
        self._load_config_file()

    def _load_config_file(self) -> None:
        path = self.config_file
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self._apply_nested_updates(data)

    def _apply_nested_updates(self, data: dict[str, Any]) -> None:
        """Flatten nested config updates and set attributes on self."""
        flat: dict[str, Any] = {}

        def _flatten(obj: Any, prefix: str = "") -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_prefix = f"{prefix}.{key}" if prefix else key
                    _flatten(value, new_prefix)
            else:
                flat[prefix] = obj

        _flatten(data)
        for nested_key, value in flat.items():
            attr = _NESTED_KEY_MAP.get(nested_key, nested_key)
            if hasattr(self, attr):
                if value is None:
                    continue
                current = getattr(self, attr)
                expected_type = type(current)
                try:
                    if expected_type is tuple and isinstance(value, list):
                        setattr(self, attr, tuple(value))
                    else:
                        setattr(self, attr, expected_type(value))
                except (TypeError, ValueError):
                    setattr(self, attr, value)

    @property
    def resolved_proxy_chain(self) -> list[str]:
        """Return proxy chain: Tor -> user proxy -> direct."""
        proxies: list[str] = []
        if self.tor_enabled:
            proxies.append(f"socks5://{self.tor_socks5_host}:{self.tor_socks5_port}")
        if self.proxy_enabled and self.proxy_url:
            if self.proxy_username:
                netloc = (
                    self.proxy_url.split("://")[1] if "://" in self.proxy_url else self.proxy_url
                )
                proxies.append(
                    f"{self.proxy_type}://{self.proxy_username}:{self.proxy_password}@{netloc}"
                )
            else:
                proxies.append(self.proxy_url)
        return proxies

    @property
    def resolved_proxy_url(self) -> str | None:
        """Return the first proxy in the chain, or None for direct connection."""
        chain = self.resolved_proxy_chain
        return chain[0] if chain else None

    def to_api_dict(self) -> dict[str, Any]:
        """Return the nested config representation used by the /v1/config API."""
        return {
            "proxy": {
                "enabled": self.proxy_enabled,
                "type": self.proxy_type,
                "url": self.proxy_url,
                "username": self.proxy_username,
                "password": "***REDACTED***",
            },
            "tor": {
                "enabled": self.tor_enabled,
                "socks5_host": self.tor_socks5_host,
                "socks5_port": self.tor_socks5_port,
                "control_port": self.tor_control_port,
            },
            "rotation": {
                "user_agent": self.rotation_user_agent,
                "ip": self.ip_rotation,
                "timing": self.rotation_timing,
                "delay_range": list(self.rotation_delay_range),
            },
            "stealth": {
                "webdriver_override": self.webdriver_override,
                "canvas_noise": self.canvas_noise,
                "webrtc_disable": self.webrtc_disable,
                "geolocation_spoof": self.geolocation_spoof,
            },
            "retry": {
                "max_attempts": self.max_retries,
                "min_quality": self.min_quality,
                "backoff": self.retry_backoff,
            },
            "output": {
                "default_format": self.default_format,
                "max_chars": self.max_chars,
                "include_links": self.include_links,
            },
            "rate_limit": {
                "rpm": self.rate_limit_rpm,
            },
        }

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Apply nested runtime config updates and persist to disk."""
        self._apply_nested_updates(updates)
        self._persist()
        return {"status": "ok", "config": self.to_api_dict()}

    def _persist(self) -> None:
        """Write the current config to the configured JSON file."""
        path = self.config_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_api_dict(), f, indent=2)
        except OSError:
            pass

    def enable_tor(self) -> dict[str, Any]:
        """Convenience helper used by the /v1/config/profile/tor endpoint."""
        return self.update(
            {
                "tor": {"enabled": True},
                "proxy": {"enabled": True, "url": "socks5://tor:9050"},
            }
        )


# Public singleton. Modules should import this directly.
settings = PrySettings()
