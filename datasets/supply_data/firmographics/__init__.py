"""Stable firmographics facade with focused source-specific modules."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from datasets.supply_data.firmographics.hiring import (
    _JOB_BOARDS,
    _board_jobs,
    _count_hiring_openings,
)
from datasets.supply_data.firmographics.http import (
    _HEADERS,
    _RETRY_CONFIG,
    _TIMEOUT,
    _fetch_html,
    _fetch_once,
    configure_retries,
)
from datasets.supply_data.firmographics.normalization import (
    _as_money,
    _as_text,
    _empty_firmographics,
    _normalize_slug,
)
from datasets.supply_data.firmographics.partner import (
    _FIRMO_API_KEY_ENV,
    _FIRMO_API_URL,
    _as_int_any,
    _partner_firmographics,
)
from datasets.supply_data.firmographics.service import (
    _get_company_firmographics,
    get_company_firmographics,
)
from datasets.supply_data.firmographics.signals import (
    _INDUSTRY_KEYWORDS,
    _LINKEDIN_RE,
    _TECH_SIGNATURES,
    _detect_industry,
    _detect_tech_stack,
    _extract_linkedin,
)
from datasets.supply_data.firmographics.website import (
    _ANTI_BOT_MARKERS,
    _WEBSITE_CANDIDATES,
    _WEBSITE_ENV,
    _find_website,
    _is_anti_bot_page,
)

__all__ = [
    "_ANTI_BOT_MARKERS",
    "_FIRMO_API_KEY_ENV",
    "_FIRMO_API_URL",
    "_HEADERS",
    "_INDUSTRY_KEYWORDS",
    "_JOB_BOARDS",
    "_LINKEDIN_RE",
    "_RETRY_CONFIG",
    "_TECH_SIGNATURES",
    "_TIMEOUT",
    "_WEBSITE_CANDIDATES",
    "_WEBSITE_ENV",
    "_as_int_any",
    "_as_money",
    "_as_text",
    "_board_jobs",
    "_count_hiring_openings",
    "_detect_industry",
    "_detect_tech_stack",
    "_empty_firmographics",
    "_extract_linkedin",
    "_fetch_html",
    "_fetch_once",
    "_find_website",
    "_get_company_firmographics",
    "_is_anti_bot_page",
    "_normalize_slug",
    "_partner_firmographics",
    "configure_retries",
    "get_company_firmographics",
]
