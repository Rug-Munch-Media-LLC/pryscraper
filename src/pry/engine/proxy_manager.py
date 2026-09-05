"""Pry — Proxy Manager with affiliate-signup flow.
Tries free proxies first (Tor, public rotating). When premium proxy is needed,
prompts user to sign up via affiliate links. Pre-wired to 5+ providers.

Health scoring/circuit-breaker lives in :mod:`pry.engine.proxy_health`
(mixed in via :class:`ProxyHealthMixin`); the provider catalog lives in
:mod:`pry.engine.proxy_providers`. This module keeps configuration,
selection, and the signup/referral flow.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from pry.core.paths import PRY_DATA_DIR
from pry.engine.proxy_health import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    COOLDOWN_SECONDS,
    HEALTH_WINDOW_SIZE,
    ProxyHealthMixin,
)
from pry.engine.proxy_providers import (
    FREE_PROXY_SOURCES,
    PREMIUM_PROXY_PROVIDERS,
    find_provider,
    get_proxy_referral,
    get_proxy_referral_summary,
    get_proxy_referral_url,
    list_proxy_referrals,
    parse_ts as _parse_ts,
)

logger = logging.getLogger(__name__)

PROXY_DIR = PRY_DATA_DIR / "proxies"
PROXY_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProxyConfig:
    """Proxy configuration."""

    provider: str = "free"
    proxy_url: str = ""
    username: str = ""
    password: str = ""
    api_key: str = ""
    proxy_type: str = "http"
    geo: str = "auto"
    rotation: str = "per_request"
    auto_rotate: bool = True


class ProxyManager(ProxyHealthMixin):
    """Manages proxy selection, free fallbacks, and premium signup flow."""

    # Tunable health params (per-instance so tests can shrink them).
    health_window_size = HEALTH_WINDOW_SIZE
    consecutive_failure_threshold = CONSECUTIVE_FAILURE_THRESHOLD
    cooldown_seconds = COOLDOWN_SECONDS

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or PROXY_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "active_config.json"
        self.creds_file = self.data_dir / "credentials.json"
        self.health_file = self.data_dir / "proxy_health.json"
        self.active_config = self._load_config()
        self.credentials: dict[str, ProxyConfig] = self._load_credentials()
        self._health_data: dict[str, Any] = self._load_health()
        self._health_lock = threading.Lock()
        self.auto_configure_from_env()

    # ── Config / credentials persistence ────────────────────────
    def _load_config(self) -> ProxyConfig:
        if self.config_file.exists():
            try:
                return ProxyConfig(**json.loads(self.config_file.read_text()))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("proxy_state_load_failed", extra={"error": str(e)[:160]})
        return ProxyConfig()

    def _load_credentials(self) -> dict[str, ProxyConfig]:
        if self.creds_file.exists():
            try:
                data = json.loads(self.creds_file.read_text())
                return {k: ProxyConfig(**v) for k, v in data.items()}
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("proxy_state_load_failed", extra={"error": str(e)[:160]})
        return {}

    def _save_config(self) -> None:
        try:
            self.config_file.write_text(json.dumps(self.active_config.__dict__, indent=2))
        except OSError as e:
            logger.debug("proxy_config_save_failed", extra={"error": str(e)[:80]})

    def _save_credentials(self) -> None:
        try:
            data = {k: v.__dict__ for k, v in self.credentials.items()}
            self.creds_file.write_text(json.dumps(data, indent=2, default=str))
        except OSError as e:
            logger.debug("proxy_creds_save_failed", extra={"error": str(e)[:80]})

    # ── Selection ───────────────────────────────────────────────
    def get_proxy_url(self) -> str | None:
        """Get the healthiest active proxy URL. Returns None if no usable proxy configured.

        Never returns a dead/cooldown proxy: if the only candidate is tripped,
        this returns None so callers fall back to the next tier instead of
        burning the last-resort proxy tier on a known-bad endpoint.
        """
        return self.get_best_proxy()

    def _candidate_proxies(self) -> list[str]:
        """Collect the proxy URLs that are currently selectable.

        Mirrors the historical get_proxy_url() resolution per provider, but as
        a list so health scoring can pick the best one (pool > single URL).
        """
        c = self.active_config
        if c.provider == "webshare":
            pool = self.webshare_pool()
            if pool:
                return pool
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        if c.provider == "free":
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        cred = self.credentials.get(c.provider)
        if not cred:
            return []
        url = self._credential_proxy_url(cred)
        return [url] if url else []

    @staticmethod
    def _credential_proxy_url(cred: ProxyConfig) -> str | None:
        """Resolve a stored credential entry to a concrete proxy URL."""
        if cred.api_key:
            return f"http://{cred.api_key}@proxy.{cred.provider}.com:8000"
        if cred.username and cred.password:
            return f"{cred.proxy_type}://{cred.username}:{cred.password}@{cred.proxy_url}"
        if cred.proxy_url:
            return cred.proxy_url
        return None

    # ── Signup / referral flow ──────────────────────────────────
    def get_signup_link(self, provider_tag: str = "") -> str:
        """Get the affiliate signup link for a provider. Records the click for revenue tracking."""
        if not provider_tag:
            provider_tag = "brightdata"
        provider = find_provider(provider_tag) or PREMIUM_PROXY_PROVIDERS[0]
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_manager",
                user_id=os.getenv("USER", ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_track_failed", extra={"error": str(e)[:80]})
        return provider["signup_url"]

    def list_providers(self, free: bool = True, premium: bool = True) -> dict[str, Any]:
        """List all available proxy providers."""
        result: dict[str, Any] = {"free": [], "premium": []}
        if free:
            result["free"] = FREE_PROXY_SOURCES
        if premium:
            result["premium"] = PREMIUM_PROXY_PROVIDERS
        result["webshare"] = self.webshare_pool_info()
        return result

    # ── Webshare residential pool (webshare_proxy.py) ─────────────────
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
                "config": self.active_config.__dict__,
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

    def auto_configure_from_env(self) -> bool:
        """Check environment variables for proxy credentials and auto-configure."""
        # Webshare residential pool: WEBSHARE_PROXY_LIST env takes priority.
        # gopass-only availability stays lazy (on-demand via webshare_pool())
        # so a provisioned secret never surprises the active config.
        if os.getenv("WEBSHARE_PROXY_LIST") and self.webshare_pool():
            self.credentials["webshare"] = ProxyConfig(
                provider="webshare",
                proxy_url="",
                proxy_type="http",
                rotation="pool",
                auto_rotate=True,
            )
            if not self.active_config.provider or self.active_config.provider == "free":
                self.active_config = self.credentials["webshare"]
            self._save_credentials()
            self._save_config()
            return True
        for provider in PREMIUM_PROXY_PROVIDERS:
            tag = provider["tag"]
            env_prefix = f"PRY_PROXY_{tag.upper()}_"
            url = os.getenv(env_prefix + "URL")
            user = os.getenv(env_prefix + "USERNAME")
            pwd = os.getenv(env_prefix + "PASSWORD")
            api_key = os.getenv(env_prefix + "API_KEY")
            if url or (user and pwd) or api_key:
                self.credentials[tag] = ProxyConfig(
                    provider=tag,
                    proxy_url=url or f"gate.{tag}.com:8000",
                    username=user or "",
                    password=pwd or "",
                    api_key=api_key or "",
                )
                if not self.active_config.provider or self.active_config.provider == "free":
                    self.active_config = self.credentials[tag]
                self._save_credentials()
                self._save_config()
                return True
        return False

    def get_recommendation(self, last_error: str = "") -> dict[str, Any]:
        """Get a recommendation for which proxy provider to use.

        Returns: signup URL, estimated cost, why recommended.
        """
        if not self.needs_premium_proxy(last_error):
            return {"needs_premium": False, "message": "Free fallbacks sufficient"}
        provider = PREMIUM_PROXY_PROVIDERS[0]
        return {
            "needs_premium": True,
            "reason": f"Site appears blocked: '{last_error[:80]}'",
            "recommended_provider": provider["name"],
            "signup_url": self.get_signup_link(provider["tag"]),
            "estimated_cost": provider["min_price"],
            "free_trial": provider.get("free_trial", "Unknown"),
            "all_providers": PREMIUM_PROXY_PROVIDERS[:3],
        }

    def record_referral_click(self, provider_tag: str, user_id: str = "") -> str:
        """Record a referral click for a specific provider. Returns the click_id."""
        provider = find_provider(provider_tag)
        if not provider:
            return ""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            return tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_signup",
                user_id=user_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_record_failed", extra={"error": str(e)[:80]})
        return ""

    def get_recent_clicks(self, days_back: int = 30) -> list[dict[str, Any]]:
        """Get recent proxy referral clicks for revenue tracking."""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            cutoff = datetime.now(UTC).timestamp() - (days_back * 86400)
            return [
                c
                for c in tracker.clicks  # type: ignore[attr-defined]  # ReferralTracker.clicks is loaded dynamically from DB
                if c.get("source", "").startswith("proxy")
                and _parse_ts(c.get("timestamp", "")) >= cutoff
            ]
        except Exception as e:  # noqa: BLE001
            logger.debug("recent_clicks_failed", extra={"error": str(e)[:80]})
            return []

    # ── Proxy referral catalog (from proxy_referrals.py) ────────────────
    def get_proxy_referral(self, provider_tag: str) -> dict[str, Any]:
        """Get the curated referral info for a proxy provider (see proxy_providers)."""
        return get_proxy_referral(provider_tag)

    def get_proxy_referral_url(self, provider_tag: str) -> str:
        """Get just the referral URL for a proxy provider."""
        return get_proxy_referral_url(provider_tag)

    def list_proxy_referrals(self) -> list[dict[str, Any]]:
        """List all proxy provider referrals (curated, marketing-friendly view)."""
        return list_proxy_referrals()

    def get_proxy_referral_summary(self) -> dict[str, Any]:
        """Return a per-tier summary of proxy referrals."""
        return get_proxy_referral_summary()
