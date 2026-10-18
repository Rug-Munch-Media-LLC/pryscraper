"""Pry — cookie warmer configuration: user agent + warming targets."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from pathlib import Path

from pry.core.paths import PRY_DATA_DIR

#: Runtime data dir — never the package tree (installed packages are read-only
#: and writing session cookies next to the source leaks them into images).
WARMER_DIR = PRY_DATA_DIR / "warmed_cookies"
WARMER_DIR.mkdir(parents=True, exist_ok=True)

# Realistic pages to "warm" cookies against (common referrers/browsing paths)
WARMING_PAGES = {
    "amazon": [
        "https://www.amazon.com/",
        "https://www.amazon.com/gp/help/customer/contact-us",
        "https://www.amazon.com/privacy",
        "https://www.amazon.com/conditions-of-use",
    ],
    "ebay": [
        "https://www.ebay.com/",
        "https://www.ebay.com/help/home",
        "https://www.ebay.com/myp/PurchaseHistory",
    ],
    "shopify": ["https://www.shopify.com/", "https://www.shopify.com/pricing"],
    "twitter": [
        "https://twitter.com/",
        "https://twitter.com/explore",
        "https://twitter.com/settings/account",
    ],
    "linkedin": ["https://www.linkedin.com/", "https://www.linkedin.com/help/intro"],
    "generic": [
        "https://www.google.com/",
        "https://en.wikipedia.org/wiki/Main_Page",
        "https://github.com/",
    ],
}


def tier_user_agent() -> str:
    """The UA the render tier actually sends — read at call time.

    Kept in one place so warmed cookies cannot claim a browser version the
    scraper never presents (a UA mismatch is a bot signal).
    """
    from pry.engine.methods import _common

    return _common._DEFAULT_USER_AGENT


def warmer_path(warmer_dir: Path, session_id: str) -> Path:
    """Path of the warmed-cookie JSON for one session."""
    return Path(warmer_dir) / f"{session_id}.json"
