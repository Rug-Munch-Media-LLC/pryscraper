# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Email body extraction — structured fields plus loose amounts/dates/URLs."""

import re
from typing import Any

from pry.engine.email_scraper.patterns import (
    classify_email,
    extract_fields,
    get_patterns_for_type,
)


def extract_email_data(subject: str, body: str, sender: str) -> dict[str, Any]:
    """Extract structured data from an email body.

    Returns extracted order/invoice/receipt information with confidence scores.
    """
    result: dict[str, Any] = {
        "sender": sender,
        "subject": subject,
        "email_type": classify_email(subject, body),
        "extracted_data": {},
    }

    patterns = get_patterns_for_type(result["email_type"])
    result["extracted_data"] = extract_fields(body, patterns)

    # Extract monetary amounts
    amounts = re.findall(r"\$?([0-9]+(?:\.[0-9]{2})?)", body)
    if amounts and "total_amount" not in result["extracted_data"]:
        # Take the largest amount as most significant
        numeric = [float(a) for a in amounts if re.match(r"^\d+\.?\d*$", a)]
        if numeric:
            result["extracted_data"]["potential_amount"] = max(numeric)

    # Extract dates
    dates = re.findall(r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", body)
    if dates:
        result["extracted_data"]["dates_found"] = dates[:3]

    # Extract URLs
    urls = re.findall(r'https?://(?:www\.)?[^\s<>"]+', body)
    if urls:
        result["extracted_data"]["urls_found"] = urls[:5]

    return result
