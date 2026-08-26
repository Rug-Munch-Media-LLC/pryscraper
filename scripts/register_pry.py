#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Submit Pry to MCP and x402 marketplace registries.

Usage:
    python scripts/register_pry.py --dry-run    # Preview submissions
    python scripts/register_pry.py --submit     # Submit to registries
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from pry.api.registry_listing import (
    MCP_REGISTRIES,
    X402_REGISTRIES,
    generate_registry_submissions,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def preview_submissions() -> None:
    """Preview what would be submitted to registries."""
    submissions = generate_registry_submissions()

    print("=" * 60)
    print("PRY REGISTRY SUBMISSIONS (DRY RUN)")
    print("=" * 60)

    for registry_type, listing in submissions.items():
        print(f"\n{registry_type.upper()} LISTING:")
        print("-" * 40)
        print(json.dumps(listing, indent=2))

    print(f"\n\nMCP REGISTRIES ({len(MCP_REGISTRIES)}):")
    for name, info in MCP_REGISTRIES.items():
        print(f"  - {name}: {info['url']}")

    print(f"\nX402 REGISTRIES ({len(X402_REGISTRIES)}):")
    for name, info in X402_REGISTRIES.items():
        print(f"  - {name}: {info['url']}")


def submit_to_registries() -> None:
    """Submit Pry to MCP and x402 registries."""

    submissions = generate_registry_submissions()
    errors: list[str] = []

    # Submit to MCP registries
    logger.info("Submitting to MCP registries...")
    for name, info in MCP_REGISTRIES.items():
        logger.info(f"  {name}: {info['url']}{info['submit']}")
        logger.info(f"    (Manual submission required - visit {info['url']})")

    # Submit to x402 registries
    logger.info("Submitting to x402 registries...")
    for name, info in X402_REGISTRIES.items():
        logger.info(f"  {name}: {info['url']}{info['submit']}")
        logger.info(f"    (Manual submission required - visit {info['url']})")

    # Output submission files
    output_dir = Path(__file__).parent.parent / "registry_submissions"
    output_dir.mkdir(exist_ok=True)

    for registry_type, listing in submissions.items():
        output_file = output_dir / f"{registry_type}_listing.json"
        output_file.write_text(json.dumps(listing, indent=2))
        logger.info(f"Saved: {output_file}")

    # Output .well-known files for hosting
    well_known_dir = Path(__file__).parent.parent / "well-known"
    well_known_dir.mkdir(exist_ok=True)

    x402_manifest = {
        "name": "Pry Scraping API",
        "description": "Pay-per-request web scraping with x402 payments",
        "version": "2.0.0",
        "payment": {
            "x402": {
                "enabled": True,
                "facilitator": "self-hosted",
                "supported_networks": [
                    "eip155:8453",
                    "eip155:1",
                    "eip155:42161",
                    "eip155:10",
                    "eip155:137",
                    "solana:mainnet",
                    "tron:mainnet",
                ],
                "supported_assets": ["USDC", "USDT", "ETH", "SOL", "TRX", "ARB", "POL", "WETH"],
            }
        },
    }
    (well_known_dir / "x402.json").write_text(json.dumps(x402_manifest, indent=2))

    agent_card = {
        "name": "Pry Scraping Agent",
        "description": "Web scraping agent with x402 payments",
        "version": "2.0.0",
        "capabilities": ["web_scraping", "data_extraction", "captcha_solving", "auto_signup"],
        "payment": {"x402": True, "crypto": ["BTC", "ETH", "SOL", "USDC", "USDT", "TRX"]},
    }
    (well_known_dir / "agent.json").write_text(json.dumps(agent_card, indent=2))

    if errors:
        logger.error(f"Errors: {'; '.join(errors)}")
        raise SystemExit(1)

    logger.info("Done! Submit the JSON files in registry_submissions/ to each marketplace.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Register Pry with MCP and x402 marketplaces")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview submissions without sending"
    )
    parser.add_argument("--submit", action="store_true", help="Submit to registries")
    args = parser.parse_args()

    if args.submit:
        submit_to_registries()
    else:
        preview_submissions()


if __name__ == "__main__":
    main()
