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
import logging
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

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
    "tor.host": "tor_host",
    "tor.port": "tor_port",
    "tor.timeout": "tor_timeout",
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

    # LLM providers — BYOK (bring your own key).
    # Consumers set these (PRY_<NAME>_API_KEY env, or the provider's standard
    # env var) to enable each AI feature. One account per provider; multi-key
    # fan-out is a deployment concern, not a product setting.
    ollama_url: str = "http://localhost:11434"
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    kilocode_api_key: str = ""
    kilocode_base_url: str = ""  # set KILOCODE_BASE_URL to your gateway
    kimi_api_key: str = ""
    nvidia_api_key: str = ""
    nous_api_key: str = ""
    zai_api_key: str = ""
    cerebras_api_key: str = ""
    minimax_api_key: str = ""
    siliconflow_api_key: str = ""
    opencode_zen_api_key: str = ""

    # Services
    flaresolverr_url: str = "http://flaresolverr:8191/v1"
    # SECURITY (2026-08-20 audit, P0-4): the original hardcoded default was a
    # published static secret — anyone reading this OSS repo could forge
    # webhook signatures. Now fail-closed with NO static default: if neither
    # PRY_WEBHOOK_SECRET env nor the secrets backend (gopass
    # pry/webhook_secret) provides a value, _ensure_webhook_secret()
    # generates a random 32-byte hex secret at boot and logs a warning that
    # it is EPHEMERAL (does not survive restarts). Operators MUST set
    # PRY_WEBHOOK_SECRET in production.
    webhook_secret: str = ""

    # CAPTCHA solving (see captcha_solver.py + captcha/ package)
    captcha_enabled: bool = True
    # 2captcha-style API key (also used by anti-captcha.com / capmonster clones)
    captcha_2captcha_api_key: str = ""
    # Capsolver API key (https://www.capsolver.com)
    captcha_capsolver_api_key: str = ""
    # OCR backend for image captchas: "tesseract" (pytesseract) | "easyocr" | "auto"
    captcha_ocr_backend: str = "tesseract"
    # DeathByCaptcha credentials (https://www.deathbycaptcha.com)
    captcha_deathbycaptcha_username: str = ""
    captcha_deathbycaptcha_password: str = ""
    # NextCaptcha API key (https://nextcaptcha.com)
    captcha_nextcaptcha_api_key: str = ""

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

    # Tor fallback (tor_fallback.py) — canonical fields used by the
    # standalone fetch_via_tor() helper. The legacy tor_socks5_* fields
    # above remain for the resolved_proxy_chain path.
    tor_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("PRY_TOR_HOST", "TOR_HOST"),
    )
    tor_port: int = Field(
        default=9050,
        validation_alias=AliasChoices("PRY_TOR_PORT", "TOR_PORT"),
    )
    tor_timeout: float = Field(
        default=30.0,
        validation_alias=AliasChoices("PRY_TOR_TIMEOUT", "TOR_TIMEOUT"),
    )

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
    webdriver_override: bool = True
    canvas_noise: bool = True
    webrtc_disable: bool = True
    geolocation_spoof: bool = True

    # Output
    default_format: str = "markdown"
    max_chars: int = 100000
    include_links: bool = True

    # Storage
    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        validation_alias=AliasChoices("PRY_CONFIG_FILE", "CONFIG_FILE"),
    )

    # Sports data (sports_data/ package) — The Odds API
    # Live odds key (https://the-odds-api.com). Free tier: 500
    # requests/month. Without a key the sports_data modules degrade to ESPN
    # public scoreboards. Also resolved via the secrets backend under the
    # name "odds_api_key" (see _apply_secrets_backend).
    odds_api_key: str = ""
    # In-memory TTL for cached odds/stats/scores (seconds). Bots poll
    # sub-minute; a ~10s TTL collapses upstream calls ~6x and keeps reads
    # sub-100ms.
    sports_odds_cache_ttl_seconds: int = Field(default=10, ge=1)
    # Sustained upstream request budget for The Odds API (requests/min),
    # enforced by the sports_data.cache token-bucket rate limiter.
    sports_odds_rate_limit_rpm: int = Field(default=30, ge=1)

    def model_post_init(self, __context: Any) -> None:
        """Post-init: pull sensitive fields from secrets_backend, then config file."""
        self._apply_secrets_backend()
        self._load_config_file()
        self._ensure_webhook_secret()

    def _ensure_webhook_secret(self) -> None:
        """Fail-closed: never run with an empty webhook signing secret.

        If no value was supplied via PRY_WEBHOOK_SECRET env, the secrets
        backend (gopass pry/webhook_secret) or the config file, generate a
        random 32-byte hex secret at boot. The generated value is EPHEMERAL:
        it changes on every restart, so webhook receivers cannot validate
        signatures across deployments unless an explicit secret is configured.
        """
        if self.webhook_secret:
            return
        self.webhook_secret = secrets.token_hex(32)  # 32 random bytes as hex
        logger.warning(
            "webhook_secret not configured (PRY_WEBHOOK_SECRET / gopass "
            "pry/webhook_secret) — generated an EPHEMERAL random signing "
            "secret that will not survive restarts. Set PRY_WEBHOOK_SECRET "
            "in production."
        )

    def _apply_secrets_backend(self) -> None:
        """Override sensitive fields with values from secrets_backend if present.

        Priority per field:
          1. secrets_backend.get_secret(name)        # gopass/env/file/auto
          2. PRY_<NAME> env var (handled by BaseSettings)
          3. field default

        Sensitive fields: api_key, *_api_key, webhook_secret, jwt_secret,
        database_url, x402_wallet, x402_facilitator. We only override if
        the field is currently empty (i.e. nothing was provided via env or
        the field default is empty).
        """
        sensitive = (
            "api_key",
            "openrouter_api_key",
            "openai_api_key",
            "anthropic_api_key",
            "cohere_api_key",
            "deepseek_api_key",
            "gemini_api_key",
            "groq_api_key",
            "mistral_api_key",
            "kilocode_api_key",
            "kimi_api_key",
            "nvidia_api_key",
            "nous_api_key",
            "zai_api_key",
            "cerebras_api_key",
            "minimax_api_key",
            "siliconflow_api_key",
            "opencode_zen_api_key",
            "webhook_secret",
            "captcha_2captcha_api_key",
            "captcha_capsolver_api_key",
            "odds_api_key",
            "captcha_deathbycaptcha_username",
            "captcha_deathbycaptcha_password",
            "captcha_nextcaptcha_api_key",
        )
        try:
            from secrets_backend import get_secret
        except ImportError:
            return
        for fname in sensitive:
            current = getattr(self, fname, None)
            if current:
                continue
            value = get_secret(fname)
            if value:
                setattr(self, fname, value)

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
                "host": self.tor_host,
                "port": self.tor_port,
                "timeout": self.tor_timeout,
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
