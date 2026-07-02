"""PryScraper — global configuration.

Loads settings from environment variables (via Pydantic Settings).
All secrets come from gopass, never from .env files committed to git.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """PryScraper application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    app_name: str = "PryScraper"
    app_version: str = "3.0.0"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    port: int = 8002

    # Database
    database_url: str = "postgresql+asyncpg://pry:pry@localhost/pry"

    # Cache
    redis_url: str = "redis://localhost:6379/0"

    # LLM Providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    # Stealth
    stealth_enabled: bool = True
    random_user_agent: bool = True
    min_delay_ms: int = 500
    max_delay_ms: int = 3000

    # Rate limiting
    rate_limit_per_domain: int = 10  # requests per second
    rate_limit_per_ip: int = 60

    # x402 Payment
    x402_enabled: bool = False
    x402_pay_to: str = ""

    # MCP
    mcp_enabled: bool = True
    mcp_tools_count: int = 8

    # Storage
    screenshot_dir: Path = Path("/tmp/pry-screenshots")  # nosec B108
    cache_ttl_seconds: int = 3600


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
