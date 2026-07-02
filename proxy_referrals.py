# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

"""Proxy provider referral links — monetize Pry by referring users to proxy services."""
from __future__ import annotations

# Each provider has a referral URL and commission structure
# When a user configures a proxy through Pry, we can offer a discount link
# that earns us a commission on their subscription

PROVIDER_REFERRALS = {
    "brightdata": {
        "name": "Bright Data",
        "referral_url": "https://brightdata.com/cp/start?promo=munchcrawl",
        "promo_code": "MUNCHCRAWL30",
        "commission": "Up to $500/mo per referral (recurring)",
        "description": "30% first payment bonus. Best residential proxies on the market.",
        "tier": "premium",
    },
    "oxylabs": {
        "name": "Oxylabs",
        "referral_url": "https://oxylabs.io/?tap_a=114931-8c3b7a&tap_s=3621085-4c2e5b",
        "commission": "30% recurring commission",
        "description": "Enterprise-grade proxies. Great for heavy scraping.",
        "tier": "premium",
    },
    "smartproxy": {
        "name": "Smartproxy",
        "referral_url": "https://smartproxy.com/?utm_source=partner&utm_medium=referral&partner=munchcrawl",
        "commission": "20% recurring commission",
        "description": "Good value residential and datacenter proxies.",
        "tier": "standard",
    },
    "iproyal": {
        "name": "IPRoyal",
        "referral_url": "https://iproyal.com/?r=munchcrawl",
        "promo_code": "PRY20",
        "commission": "25% recurring commission + $20 bonus for referred user",
        "description": "Budget-friendly residential proxies. Pay-per-IP option.",
        "tier": "budget",
    },
    "webshare": {
        "name": "Webshare",
        "referral_url": "https://webshare.io/?referral=munchcrawl",
        "promo_code": "PRYFREE10",
        "commission": "$1 per referral + 10% recurring",
        "description": "Free tier available. Cheap datacenter proxies.",
        "tier": "budget",
    },
}
