"""Pry - MCP tool definitions: x402 billing tools (pricing, balance, packs, referrals)..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_x402_pricing",
        "description": (
            "Get current x402 pay-per-call pricing for all Pry operations, showing the cost in "
            "USDC atomic units and supported networks for each tool. "
            "Use before a paid call to display the cost to the user, e.g. 'how much does a "
            "pry_scrape cost?'."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "facilitator": {"type": "string"},
                        "supported_networks": {"type": "array", "items": {"type": "string"}},
                        "wallets": {"type": "object"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_balance",
        "description": (
            "Read the prepaid balance of a Pry account (bulk scrape credits purchased via "
            "crypto). Pass your pry API key (e.g. api_key='pry_abc123_deadbeef...') or a "
            "user_id to see the USD balance + low-balance flag. Use before buying a pack to "
            "confirm you can afford an operation, or after a purchase to confirm the credit "
            "landed (e.g. after a 5000-credit starter pack you should see ~5.00 USD). This is "
            "a free read of your own account — it does not spend credits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "description": "The pry API key whose owner's balance to read.",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional explicit account id (takes precedence over api_key).",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "balance": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"},
                                "balance_usd": {"type": "number"},
                                "low_balance": {"type": "boolean"},
                            },
                        }
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_buy_pack",
        "description": (
            "Initiate a crypto purchase of a bulk scrape-credit pack. Pass a pack id "
            "(e.g. pack_id='starter' for $5/5,000 credits) and it returns a spec-compliant "
            "x402 PaymentRequired manifest with the real receiving wallet as payToAddress and "
            "the server-authoritative price in atomic units. The agent/partner pays USDC "
            "on-chain (or the quoted asset, defaults to the configured network), then calls the "
            "confirm endpoint with the tx hash to credit the balance — and on first purchase an "
            "API key is minted. An empty payToAddress in the response means the operator hasn't "
            "configured a receiving wallet; never pay a placeholder address."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_id": {
                    "type": "string",
                    "default": "starter",
                    "description": "Credit-pack id: starter ($5/5,000 credits), growth ($20/20,000), bulk ($100/100,000).",
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional API key whose owner receives the credits (else a key is minted on purchase).",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional explicit account id to credit.",
                },
                "network": {
                    "type": "string",
                    "description": "Optional CAIP-2 / legacy x402 network (defaults to the configured default).",
                },
                "asset": {
                    "type": "string",
                    "default": "USDC",
                    "description": "Optional asset to pay in (defaults to USDC).",
                },
            },
            "required": ["pack_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "status_code": {"type": "integer"},
                        "payment_required": {"type": "object"},
                        "invoice_id": {"type": "string"},
                        "pack_id": {"type": "string"},
                        "amount_usd": {"type": "number"},
                        "amount_atomic": {"type": "integer"},
                        "credits": {"type": "integer"},
                        "chain": {"type": "string"},
                        "pay_to": {"type": "string"},
                        "asset": {"type": "string"},
                        "expires_at": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_referrals",
        "description": (
            "Get Pry's referral catalog — 60+ providers across LLM, hosting, email, "
            "monitoring, proxies, and devtools — each link carrying our affiliate ID for "
            "revenue attribution. "
            "Use to find a revenue-share partner or pick a recommended provider, e.g. "
            "'what proxy providers do you refer?'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter the catalog by category (e.g., 'proxies', 'llm', 'hosting')",
                }
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "description": (
                        "Referral catalog entries. Without a category filter each "
                        "entry is {category, providers}; with one, each entry is a "
                        "bare provider record."
                    ),
                    "items": {"type": "object"},
                },
            },
            "required": ["success"],
        },
    },
]
