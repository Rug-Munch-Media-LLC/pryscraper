"""Pry — Proxy Manager with affiliate-signup flow.
Tries free proxies first (Tor, public rotating). When premium proxy is needed,
prompts user to sign up via affiliate links. Pre-wired to 5+ providers."""
from paths import PRY_DATA_DIR

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from proxy_referrals import PROVIDER_REFERRALS as _PROXY_REFERRALS
except ImportError:  # proxy_referrals module not always present in slim installs
    _PROXY_REFERRALS = {}

PROXY_DIR = PRY_DATA_DIR / "proxies"
PROXY_DIR.mkdir(parents=True, exist_ok=True)

# Free proxy sources (no signup required)
FREE_PROXY_SOURCES = [
    {
        "name": "Tor",
        "type": "socks5",
        "url": "socks5://127.0.0.1:9050",
        "cost": "Free",
        "speed": "Slow",
        "reliability": "High",
    },
    {
        "name": "Public Pool (round-robin)",
        "type": "http",
        "url": "rotating",
        "cost": "Free",
        "speed": "Variable",
        "reliability": "Low",
    },
    {
        "name": "Cloudflare WARP",
        "type": "wireguard",
        "url": "warp://1.1.1.1",
        "cost": "Free",
        "speed": "Fast",
        "reliability": "High",
    },
]

# Premium proxy providers with full affiliate details
PREMIUM_PROXY_PROVIDERS = [
    {
        "name": "Bright Data",
        "tag": "brightdata",
        "url": "https://brightdata.com/?ref=pry",
        "signup_url": "https://brightdata.com/cp/start?aff_id=pry",
        "api_endpoint": "https://api.brightdata.com",
        "auth_format": "username:password",
        "commission": "$2-$50 per signup, up to 10% recurring",
        "cookie_days": 30,
        "free_trial": "Yes, $5 credit",
        "min_price": "$0.10/GB residential",
        "speed": "Very Fast",
        "reliability": "Very High",
        "ips": "72M+ residential, 770K+ datacenter",
        "geo_coverage": "195 countries",
        "protocols": ["HTTP", "SOCKS5", "HTTPS"],
        "note": "Industry leader. Best for high-volume scraping.",
    },
    {
        "name": "Smartproxy",
        "tag": "smartproxy",
        "url": "https://smartproxy.com/?ref=pry",
        "signup_url": "https://dashboard.smartproxy.com/registration?aff_id=pry",
        "api_endpoint": "https://api.smartproxy.com",
        "auth_format": "username:password",
        "commission": "20% recurring lifetime",
        "cookie_days": 60,
        "free_trial": "Yes, 100MB",
        "min_price": "$0.10/GB residential",
        "speed": "Fast",
        "reliability": "High",
        "ips": "40M+ residential",
        "geo_coverage": "195 countries",
        "protocols": ["HTTP", "SOCKS5"],
        "note": "Good balance of price and quality.",
    },
    {
        "name": "Oxylabs",
        "tag": "oxylabs",
        "url": "https://oxylabs.io/?ref=pry",
        "signup_url": "https://dashboard.oxylabs.io/?aff_id=pry",
        "api_endpoint": "https://api.oxylabs.com",
        "auth_format": "username:password",
        "commission": "Partner program (10-30% recurring)",
        "cookie_days": 30,
        "free_trial": "Yes, 5K requests",
        "min_price": "$1.20/GB residential",
        "speed": "Very Fast",
        "reliability": "Very High",
        "ips": "100M+ residential",
        "geo_coverage": "195 countries",
        "protocols": ["HTTP", "SOCKS5", "HTTPS"],
        "note": "Enterprise-grade. Best for big data scraping.",
    },
    {
        "name": "IPRoyal",
        "tag": "iproyal",
        "url": "https://iproyal.com/?ref=pry",
        "signup_url": "https://dashboard.iproyal.com/signup?aff=pry",
        "api_endpoint": "https://api.iproyal.com",
        "auth_format": "username:password",
        "commission": "30% recurring lifetime",
        "cookie_days": 60,
        "free_trial": "No",
        "min_price": "$0.04/GB residential",
        "speed": "Medium",
        "reliability": "High",
        "ips": "300K+ residential",
        "geo_coverage": "150+ countries",
        "protocols": ["HTTP", "SOCKS5"],
        "note": "Cheapest. Good for budget scraping.",
    },
    {
        "name": "Webshare",
        "tag": "webshare",
        "url": "https://www.webshare.io/?ref=pry",
        "signup_url": "https://proxy.webshare.io/register?aff=pry",
        "api_endpoint": "https://proxy.webshare.io/api/v2",
        "auth_format": "api_key",
        "commission": "30% recurring lifetime",
        "cookie_days": 60,
        "free_trial": "Yes, 10 free proxies",
        "min_price": "$0.03/proxy/month (datacenter)",
        "speed": "Very Fast",
        "reliability": "High",
        "ips": "500K+ datacenter/residential",
        "geo_coverage": "100+ countries",
        "protocols": ["HTTP", "SOCKS5"],
        "note": "Best free tier. Try before you buy.",
    },
    {
        "name": "Proxy-Seller",
        "tag": "proxyseller",
        "url": "https://proxy-seller.com/?ref=pry",
        "signup_url": "https://proxy-seller.com/?partner=pry",
        "auth_format": "username:password",
        "commission": "30% recurring",
        "cookie_days": 60,
        "free_trial": "No",
        "min_price": "$1.40/proxy/month",
        "speed": "Fast",
        "reliability": "High",
        "note": "Cheap private proxies.",
    },
    {
        "name": "NetNut",
        "tag": "netnut",
        "url": "https://netnut.io/?ref=pry",
        "signup_url": "https://netnut.io/?aff=pry",
        "auth_format": "username:password",
        "commission": "Partner program",
        "cookie_days": 30,
        "free_trial": "Yes, 7 days",
        "min_price": "$0.20/GB",
        "note": "Fast residential IPs from ISPs.",
    },
    {
        "name": "ProxyMesh",
        "tag": "proxymesh",
        "url": "https://proxymesh.com/?ref=pry",
        "signup_url": "https://proxymesh.com/?aff=pry",
        "auth_format": "username:password",
        "commission": "20% recurring",
        "cookie_days": 30,
        "free_trial": "No",
        "min_price": "$0.80/proxy",
        "note": "Simple rotating proxies.",
    },
    {
        "name": "Decodo (Smartproxy)",
        "tag": "decodo",
        "url": "https://decodo.com/?ref=pry",
        "signup_url": "https://decodo.com/signup?aff=pry",
        "auth_format": "username:password",
        "commission": "20% recurring",
        "cookie_days": 60,
        "note": "Budget option from Smartproxy.",
    },
    {
        "name": "PacketStream",
        "tag": "packetstream",
        "url": "https://packetstream.io/?ref=pry",
        "signup_url": "https://packetstream.io/signup?aff=pry",
        "auth_format": "username:password",
        "commission": "20% revenue share",
        "cookie_days": 60,
        "free_trial": "Pay-as-you-go",
        "min_price": "$0.05/GB",
        "note": "Bandwidth-sharing residential proxies.",
    },
]


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


class ProxyManager:
    """Manages proxy selection, free fallbacks, and premium signup flow."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or PROXY_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "active_config.json"
        self.creds_file = self.data_dir / "credentials.json"
        self.active_config = self._load_config()
        self.credentials: dict[str, ProxyConfig] = self._load_credentials()
        self.auto_configure_from_env()

    def _load_config(self) -> ProxyConfig:
        if self.config_file.exists():
            try:
                return ProxyConfig(**json.loads(self.config_file.read_text()))
            except (json.JSONDecodeError, TypeError):
                pass
        return ProxyConfig()

    def _load_credentials(self) -> dict[str, ProxyConfig]:
        if self.creds_file.exists():
            try:
                data = json.loads(self.creds_file.read_text())
                return {k: ProxyConfig(**v) for k, v in data.items()}
            except (json.JSONDecodeError, TypeError):
                pass
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

    def get_proxy_url(self) -> str | None:
        """Get the active proxy URL. Returns None if no proxy configured."""
        c = self.active_config
        if c.provider == "free":
            if c.proxy_url and c.proxy_url != "rotating":
                return c.proxy_url
            return None
        if c.provider not in self.credentials:
            return None
        cred = self.credentials[c.provider]
        if cred.api_key:
            return f"http://{cred.api_key}@proxy.{cred.provider}.com:8000"
        if cred.username and cred.password:
            return f"{cred.proxy_type}://{cred.username}:{cred.password}@{cred.proxy_url}"
        if cred.proxy_url:
            return cred.proxy_url
        return None

    def test_proxy(
        self, proxy_url: str, test_url: str = "https://httpbin.org/ip", timeout: int = 10
    ) -> dict[str, Any]:
        """Test a proxy and return its public IP, latency, and working status."""
        import httpx

        start = time.time()
        try:
            with httpx.Client(proxy=proxy_url, timeout=timeout) as c:
                r = c.get(test_url)
                elapsed = time.time() - start
                return {
                    "working": r.is_success,
                    "latency": round(elapsed, 2),
                    "ip": r.text[:100] if r.is_success else "",
                    "status": r.status_code,
                }
        except Exception as e:
            return {"working": False, "error": str(e)[:100]}

    def needs_premium_proxy(self, last_error: str) -> bool:
        """Determine if we need a premium proxy based on the error type."""
        indicators = [
            "captcha",
            "cloudflare",
            "datadome",
            "akamai",
            "403",
            "429",
            "rate limit",
            "blocked",
        ]
        return any(i in last_error.lower() for i in indicators)

    def get_signup_link(self, provider_tag: str = "") -> str:
        """Get the affiliate signup link for a provider. Records the click for revenue tracking."""
        if not provider_tag:
            provider_tag = "brightdata"
        provider = next((p for p in PREMIUM_PROXY_PROVIDERS if p["tag"] == provider_tag), None)
        if not provider:
            provider = PREMIUM_PROXY_PROVIDERS[0]
        try:
            from referrals import ReferralTracker

            tracker = ReferralTracker()
            tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_manager",
                user_id=os.getenv("USER", ""),
            )
        except Exception as e:
            logger.debug("referral_track_failed", extra={"error": str(e)[:80]})
        return provider["signup_url"]

    def list_providers(self, free: bool = True, premium: bool = True) -> dict[str, Any]:
        """List all available proxy providers."""
        result: dict[str, Any] = {"free": [], "premium": []}
        if free:
            result["free"] = FREE_PROXY_SOURCES
        if premium:
            result["premium"] = PREMIUM_PROXY_PROVIDERS
        return result

    def select_provider(self, provider_tag: str, credentials: dict | None = None) -> dict[str, Any]:
        """Select a premium provider. If credentials provided, save them."""
        provider = next((p for p in PREMIUM_PROXY_PROVIDERS if p["tag"] == provider_tag), None)
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
        provider = next((p for p in PREMIUM_PROXY_PROVIDERS if p["tag"] == provider_tag), None)
        if not provider:
            return ""
        try:
            from referrals import ReferralTracker

            tracker = ReferralTracker()
            return tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_signup",
                user_id=user_id,
            )
        except Exception as e:
            logger.debug("referral_record_failed", extra={"error": str(e)[:80]})
        return ""

    def get_recent_clicks(self, days_back: int = 30) -> list[dict[str, Any]]:
        """Get recent proxy referral clicks for revenue tracking."""
        try:
            from referrals import ReferralTracker

            tracker = ReferralTracker()
            cutoff = datetime.now(UTC).timestamp() - (days_back * 86400)
            return [
                c
                for c in tracker.clicks
                if c.get("source", "").startswith("proxy")
                and _parse_ts(c.get("timestamp", "")) >= cutoff
            ]
        except Exception as e:
            logger.debug("recent_clicks_failed", extra={"error": str(e)[:80]})
            return []


    # ── Proxy referral catalog (from proxy_referrals.py) ────────────────
    def get_proxy_referral(self, provider_tag: str) -> dict[str, Any]:
        """Get the curated referral info for a proxy provider.

        Returns the proxy_referrals.PROVIDER_REFERRALS entry for the given tag
        (e.g., 'brightdata', 'iproyal'). Empty dict if not found.

        This is the affiliate-friendly subset: it gives the marketing-y details
        (commission, promo code, tier) that are useful when prompting a user to
        sign up for a premium proxy. The full proxy connection config
        (host, port, auth) lives in PREMIUM_PROXY_PROVIDERS.
        """
        return _PROXY_REFERRALS.get(provider_tag, {})

    def get_proxy_referral_url(self, provider_tag: str) -> str:
        """Get just the referral URL for a proxy provider."""
        entry = _PROXY_REFERRALS.get(provider_tag, {})
        return entry.get("referral_url", "")

    def list_proxy_referrals(self) -> list[dict[str, Any]]:
        """List all proxy provider referrals (curated, marketing-friendly view)."""
        return [
            {"tag": tag, **info} for tag, info in _PROXY_REFERRALS.items()
        ]

    def get_proxy_referral_summary(self) -> dict[str, Any]:
        """Return a per-tier summary of proxy referrals (count, providers, total commission ceiling)."""
        tiers: dict[str, list[str]] = {"premium": [], "standard": [], "budget": []}
        for tag, info in _PROXY_REFERRALS.items():
            tier = info.get("tier", "standard")
            tiers.setdefault(tier, []).append(tag)
        return {
            "tiers": tiers,
            "total_providers": len(_PROXY_REFERRALS),
            "by_tag": _PROXY_REFERRALS,
        }



def _parse_ts(ts: str) -> float:
    """Parse an ISO timestamp to epoch seconds. Returns 0 on error."""
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0
