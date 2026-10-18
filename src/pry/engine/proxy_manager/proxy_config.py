"""Active provider selection, env auto-config and Webshare pool access.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pry.engine.proxy_manager.proxy_types import ProxyConfig
from pry.engine.proxy_providers import (
    FREE_PROXY_SOURCES,
    PREMIUM_PROXY_PROVIDERS,
    find_provider,
)

logger = logging.getLogger(__name__)


class ProxyConfigMixin:
    """Provider catalog view, env auto-configuration and Webshare pool wiring."""

    def list_providers(self, free: bool = True, premium: bool = True) -> dict[str, Any]:
        """List all available proxy providers."""
        result: dict[str, Any] = {"free": [], "premium": []}
        if free:
            result["free"] = FREE_PROXY_SOURCES
        if premium:
            result["premium"] = PREMIUM_PROXY_PROVIDERS
        result["webshare"] = self.webshare_pool_info()
        return result

    def webshare_pool(self) -> list[str]:
        """Return the cached Webshare residential proxy pool (env or gopass)."""
        from pry.engine.webshare_proxy import load_webshare_proxies

        return load_webshare_proxies()

    def next_webshare_proxy(self) -> str | None:
        """Return the next Webshare proxy (round-robin), or None if the pool is empty."""
        from pry.engine.webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()

    def webshare_pool_info(self) -> dict[str, Any]:
        """Metadata about the Webshare pool, with credentials masked."""
        from pry.engine.webshare_proxy import mask_proxy_url, webshare_source

        pool = self.webshare_pool()
        return {
            "provider": "webshare",
            "source": webshare_source(),
            "count": len(pool),
            "proxies": [mask_proxy_url(p) for p in pool],
        }

    def _public_config(self) -> dict[str, Any]:
        """Active config safe for API responses/logs (secrets masked)."""
        data = dict(self.active_config.__dict__)
        for key in ("password", "api_key"):
            if data.get(key):
                data[key] = "***"
        return data

    def select_provider(self, provider_tag: str, credentials: dict | None = None) -> dict[str, Any]:
        """Select a premium provider. If credentials provided, save them."""
        provider = find_provider(provider_tag)
        if not provider:
            return {"success": False, "error": f"Unknown provider: {provider_tag}"}

        self.get_signup_link(provider_tag)

        if credentials:
            self.credentials[provider_tag] = ProxyConfig(
                provider=provider_tag,
                proxy_url=credentials.get("proxy_url", f"gate.{provider_tag}.com:8000"),
                username=credentials.get("username", ""),
                password=credentials.get("password", ""),
                api_key=credentials.get("api_key", ""),
                proxy_type=credentials.get("proxy_type", "http"),
            )
            self.active_config = self.credentials[provider_tag]
            self._save_credentials()
            self._save_config()
            return {
                "success": True,
                "provider": provider_tag,
                "config": self._public_config(),
            }

        return {
            "success": False,
            "needs_signup": True,
            "signup_url": provider["signup_url"],
            "message": (
                f"Visit {provider['signup_url']} to sign up for {provider['name']}, "
                "then call this endpoint again with credentials."
            ),
            "provider": provider,
        }

    def _activate_credential(self, tag: str, config: ProxyConfig) -> None:
        """Persist a credential and promote it when no premium provider is active."""
        self.credentials[tag] = config
        if not self.active_config.provider or self.active_config.provider == "free":
            self.active_config = config
        self._save_credentials()
        self._save_config()

    def _try_webshare_env(self) -> bool:
        if not (os.getenv("WEBSHARE_PROXY_LIST") and self.webshare_pool()):
            return False
        self._activate_credential(
            "webshare",
            ProxyConfig(
                provider="webshare",
                proxy_url="",
                proxy_type="http",
                rotation="pool",
                auto_rotate=True,
            ),
        )
        return True

    def _try_premium_env(self) -> bool:
        for provider in PREMIUM_PROXY_PROVIDERS:
            tag = provider["tag"]
            prefix = f"PRY_PROXY_{tag.upper()}_"
            url = os.getenv(prefix + "URL")
            user = os.getenv(prefix + "USERNAME")
            pwd = os.getenv(prefix + "PASSWORD")
            api_key = os.getenv(prefix + "API_KEY")
            if not (url or (user and pwd) or api_key):
                continue
            self._activate_credential(
                tag,
                ProxyConfig(
                    provider=tag,
                    proxy_url=url or f"gate.{tag}.com:8000",
                    username=user or "",
                    password=pwd or "",
                    api_key=api_key or "",
                ),
            )
            return True
        return False

    def auto_configure_from_env(self) -> bool:
        """Check environment variables for proxy credentials and auto-configure."""
        # Webshare residential pool: WEBSHARE_PROXY_LIST takes priority.
        # gopass-only availability stays lazy so a secret never surprises the
        # active config.
        return self._try_webshare_env() or self._try_premium_env()

__all__ = ["ProxyConfigMixin"]
