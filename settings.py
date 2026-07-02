"""Pry — centralized settings via Pydantic BaseSettings.
Every env var lives here. Import `settings` singleton everywhere else."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pydantic_settings import BaseSettings, SettingsConfigDict


class PrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core
    url: str = "http://localhost:8002"
    host: str = "0.0.0.0"
    port: int = 8002

    # Ollama LLM endpoint
    ollama_url: str = "http://100.100.18.18:11434"

    # FlareSolverr Cloudflare bypass endpoint
    flaresolverr_url: str = "http://flaresolverr:8191/v1"

    # Webhook secret for job callbacks
    webhook_secret: str = "pry-webhook-secret"

    # API key for endpoint authentication (empty = disabled)
    api_key: str = ""

    # OpenRouter API key (optional, for vision models)
    openrouter_api_key: str = ""

    # Proxy / Tor
    proxy_url: str = ""
    proxy_type: str = "http"
    proxy_username: str = ""
    proxy_password: str = ""
    tor_enabled: bool = False
    tor_socks5_host: str = "tor"
    tor_socks5_port: int = 9050

    # Rotation
    ip_rotation: str = ""
    max_retries: int = 0
    min_quality: int = 0
    rate_limit_rpm: int = 0

    # Redis (optional, for job queue persistence)
    redis_url: str = "redis://localhost:6379/0"


settings = PrySettings()
