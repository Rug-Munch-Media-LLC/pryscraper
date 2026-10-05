# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Regex patterns used to extract fields from email bodies."""

import re
from typing import Any

ORDER_PATTERNS: dict[str, list[str]] = {
    "order_number": [
        r"order\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,20})",
        r"(?:order|ord)\s*[#:]?\s*([A-Z0-9]{5,20})",
        r"confirmation\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,20})",
    ],
    "total_amount": [
        r"total[:\s]*\$?([0-9,.]+)",
        r"amount[:\s]*\$?([0-9,.]+)",
        r"charged[:\s]*\$?([0-9,.]+)",
    ],
    "tracking_number": [
        r"tracking\s*(?:#|number|id|no)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"track\s*(?:#|number)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"shipment\s*(?:#|number|id)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
    ],
    "product_name": [
        r"(?:product|item|goods)[:\s]*(.+?)(?:\n|$)",
        r"purchased[:\s]*(.+?)(?:\n|$)",
        r"ordered[:\s]*(.+?)(?:\n|$)",
    ],
    "shipping_address": [
        r"shipping\s*(?:to|address)[:\s]*([A-Za-z0-9\s,\-]{10,100})",
        r"deliver\s*(?:to|address)[:\s]*([A-Za-z0-9\s,\-]{10,100})",
    ],
}

INVOICE_PATTERNS: dict[str, list[str]] = {
    "invoice_number": [
        r"invoice\s*(?:#|number|id|no)[:\s]*([A-Z0-9\-]{5,25})",
        r"inv\s*(?:#|no)[:\s]*([A-Z0-9\-]{5,25})",
    ],
    "due_date": [
        r"due\s*(?:date|by)[:\s]*([A-Za-z0-9\s,]+)",
        r"payment\s*(?:due|by)[:\s]*([A-Za-z0-9\s,]+)",
    ],
    "vendor": [
        r"(?:from|vendor|supplier)[:\s]*(.+?)(?:\n|$)",
        r"billed\s*(?:from|by)[:\s]*(.+?)(?:\n|$)",
    ],
}

SHIPPING_PATTERNS: dict[str, list[str]] = {
    "tracking_number": [
        r"tracking\s*(?:#|number|id|no)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"track\s*(?:#|number)[:\s]*(?:is\s+)?([A-Z0-9]{8,30})",
        r"shipment\s*(?:#|number|id)[:\s]*(?:is\s+)?([A-Z0-9\-]{8,30})",
    ],
    "carrier": [
        r"(?:carrier|shipped\s*via|courier)[:\s]*(.+?)(?:\n|$)",
        r"(?:USPS|UPS|FedEx|DHL|Canada\s*Post|Royal\s*Mail)",
    ],
    "estimated_delivery": [
        r"estimated\s*(?:delivery|arrival)[:\s]*(.+?)(?:\n|$)",
        r"delivery\s*(?:date|by|on)[:\s]*([A-Za-z0-9\s,]+)",
        r"arriving\s*(?:on|by)[:\s]*([A-Za-z0-9\s,]+)",
    ],
}

RECEIPT_PATTERNS: dict[str, list[str]] = {
    "receipt_number": [
        r"receipt\s*(?:#|number)[:\s]*([A-Z0-9\-]{5,25})",
        r"transaction\s*(?:#|id)[:\s]*([A-Z0-9\-]{5,30})",
    ],
    "payment_method": [
        r"payment\s*method[:\s]*(.+?)(?:\n|$)",
        r"paid\s*via[:\s]*(.+?)(?:\n|$)",
        r"card[:\s]*([A-Za-z0-9\s]{4,30})",
    ],
    "store_name": [
        r"(?:store|merchant|seller|retailer)[:\s]*(.+?)(?:\n|$)",
        r"purchased\s*(?:from|at)[:\s]*(.+?)(?:\n|$)",
        r"thank\s*you\s*for\s*(?:your\s*)?purchase\s*(?:from|at)?[:\s]*(.+?)(?:\n|$)",
    ],
}


def classify_email(subject: str, body: str) -> str:
    """Classify an email as order_confirmation, invoice, receipt, or other."""
    combined = (subject + " " + body[:500]).lower()
    if any(
        w in combined for w in ["order confirmation", "your order", "order received", "order #"]
    ):
        return "order_confirmation"
    if any(w in combined for w in ["invoice", "payment due", "billing statement", "invoice #"]):
        return "invoice"
    if any(
        w in combined for w in ["receipt", "your receipt", "payment receipt", "transaction receipt"]
    ):
        return "receipt"
    if any(w in combined for w in ["shipping", "shipment", "tracking", "on its way", "dispatched"]):
        return "shipping_notification"
    if any(w in combined for w in ["subscription", "renewal", "billed"]):
        return "subscription"
    return "other"


def get_patterns_for_type(email_type: str) -> dict[str, list[str]]:
    """Get extraction patterns for the classified email type."""
    if email_type == "order_confirmation":
        return ORDER_PATTERNS
    if email_type == "invoice":
        return INVOICE_PATTERNS
    if email_type == "receipt":
        return RECEIPT_PATTERNS
    if email_type == "shipping_notification":
        return SHIPPING_PATTERNS
    return {}


#: Backwards-compatible alias for the historical private name.
_classify_email = classify_email


def extract_fields(body: str, patterns: dict[str, list[str]]) -> dict[str, Any]:
    """Apply each field's regex list to ``body``; first match wins per field."""
    found: dict[str, Any] = {}
    for field, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                found[field] = match.group(1).strip()
                break
    return found
