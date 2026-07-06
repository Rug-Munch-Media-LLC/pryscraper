"""Pry — Zoho CRM sync (NOT IMPLEMENTED).

Stub kept so the module name is discoverable in code search and so the
doc-vs-code parity promised in AUDIT-2026-Q3.md §"Hallucinated features"
holds: the FEATURES.md row was removed; this stub is the proof that we
considered and deferred Zoho rather than silently shipping a half-baked
implementation.

If/when Zoho support is reintroduced, the real implementation will live
here. It should follow the same shape as the other CRM backends in
``crm_sync.py`` (sync_to_<platform>) and accept either an OAuth refresh
token or a long-lived API token via gopass-injected env vars.

To enable: implement sync_to_zoho() and remove the NotImplementedError.
Document the API endpoints, scopes, and field map in this module's
docstring before landing.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from typing import Any

import httpx

ZOHO_API_BASE = "https://www.zohoapis.com/crm/v2"


async def sync_to_zoho(
    objects: list[dict[str, Any]],
    object_type: str = "Leads",
    access_token: str = "",
    api_domain: str = "https://www.zohoapis.com",
) -> dict[str, Any]:
    """Sync scraped data to Zoho CRM.

    Raises:
        NotImplementedError: Zoho sync is deferred. See AUDIT-2026-Q3.md.
    """
    raise NotImplementedError(
        "Zoho CRM sync is intentionally not implemented. "
        "See AUDIT-2026-Q3.md §Hallucinated features for rationale. "
        "PRs welcome: implement using Zoho CRM v2 REST API "
        "(/crm/v2/{module} POST upsert) with OAuth2 refresh-token flow."
    )


__all__ = ["sync_to_zoho", "ZOHO_API_BASE"]