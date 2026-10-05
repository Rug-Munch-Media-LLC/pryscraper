# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Email Inbox Scraping.

Connect Gmail/Outlook, extract structured data from emails.

This module is a thin facade: the implementation lives in focused
submodules and every public name is re-exported here so existing
``from pry.engine.email_scraper import ...`` call sites keep working.
"""

from pry.engine.email_scraper.extractor import extract_email_data
from pry.engine.email_scraper.gmail import fetch_gmail_emails
from pry.engine.email_scraper.outlook import fetch_outlook_emails
from pry.engine.email_scraper.patterns import (
    INVOICE_PATTERNS,
    ORDER_PATTERNS,
    RECEIPT_PATTERNS,
    SHIPPING_PATTERNS,
    _classify_email,
)

__all__ = [
    "INVOICE_PATTERNS",
    "ORDER_PATTERNS",
    "RECEIPT_PATTERNS",
    "SHIPPING_PATTERNS",
    "_classify_email",
    "extract_email_data",
    "fetch_gmail_emails",
    "fetch_outlook_emails",
]
