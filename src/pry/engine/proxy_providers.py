"""Pry — Proxy provider catalog (free sources + premium affiliate providers).

Pure data module: the free proxy sources, the premium provider catalog with
affiliate/signup details, and the curated proxy referral catalog loaded from
:mod:`pry.commerce.proxy_referrals` when available.

Split out of :mod:`pry.engine.proxy_manager` so the manager logic stays
focused on selection/health.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from pry.commerce.proxy_referrals import PROVIDER_REFERRALS as _PROXY_REFERRALS
except ImportError:  # proxy_referrals module not always present in slim installs
    _PROXY_REFERRALS: dict[str, dict[str, Any]] = {}

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
PREMIUM_PROXY_PROVIDERS: list[dict[str, Any]] = [
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


def find_provider(provider_tag: str) -> dict[str, Any] | None:
    """Look up a premium provider entry by its tag."""
    return next((p for p in PREMIUM_PROXY_PROVIDERS if p["tag"] == provider_tag), None)


def get_proxy_referral(provider_tag: str) -> dict[str, Any]:
    """Get the curated referral info for a proxy provider.

    Returns the proxy_referrals.PROVIDER_REFERRALS entry for the given tag
    (e.g., 'brightdata', 'iproyal'). Empty dict if not found.

    This is the affiliate-friendly subset: it gives the marketing-y details
    (commission, promo code, tier) that are useful when prompting a user to
    sign up for a premium proxy. The full proxy connection config
    (host, port, auth) lives in PREMIUM_PROXY_PROVIDERS.
    """
    return _PROXY_REFERRALS.get(provider_tag, {})


def get_proxy_referral_url(provider_tag: str) -> str:
    """Get just the referral URL for a proxy provider."""
    entry = _PROXY_REFERRALS.get(provider_tag, {})
    return entry.get("referral_url", "")


def list_proxy_referrals() -> list[dict[str, Any]]:
    """List all proxy provider referrals (curated, marketing-friendly view)."""
    return [{"tag": tag, **info} for tag, info in _PROXY_REFERRALS.items()]


def get_proxy_referral_summary() -> dict[str, Any]:
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


def parse_ts(ts: str) -> float:
    """Parse an ISO timestamp to epoch seconds. Returns 0 on error."""
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0
