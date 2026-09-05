"""Pry API routers.

Each module in this package groups FastAPI endpoints by their `tags` field
(see api.py). The original api.py had 195 endpoints across 52 tags in a
single 4,668-line file. This package splits them so each router is
~50-300 lines (per CONVENTIONS.md, no file over 500 lines).

Pattern for each router file:

    from fastapi import APIRouter, Body, Query
    from typing import Any
    from pry.core.errors import NotFoundError  # if needed

    router = APIRouter(tags=["Auth"])

    @router.post("/v1/auth/credentials", summary="...")
    async def store_credentials(...):
        ...

Then in api.py:
    from pry.api.routers.core.auth import router as auth_router
    app.include_router(auth_router)

Migration order (one router at a time, each as a separate commit):
  1. auth        - done
  2. health      - easy (3 endpoints, no business logic)
  3. scraping    - core, but well-bounded
  4. extraction  - similar
  5. ... see docs/adr/0003-api-router-split.md for the full plan

The full split is a multi-hour refactor; this package is the
infrastructure for it. The first commit (this file + routers/auth.py)
demonstrates the pattern; subsequent commits can add more routers
without changing the overall structure.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

__all__: list[str] = [
    "advanced_router",
    "agency_router",
    "ai_router",
    "alerts_router",
    "analysis_router",
    "analytics_router",
    "attention_router",
    "auth_api_router",
    "automation_router",
    "batch_router",
    "circuit_breaker_router",
    "commerce_router",
    "compliance_router",
    "config_router",
    "costing_router",
    "crm_router",
    "dashboard_router",
    "email_router",
    "enrichment_router",
    "execute_router",
    "export_router",
    "extraction_router",
    "freshness_router",
    "gdpr_router",
    "health_api_router",
    "integrations_router",
    "intelligence_router",
    "jobs_router",
    "legal_docs_router",
    "local_data_router",
    "marketplace_router",
    "monitoring_router",
    "parsing_router",
    "pipeline_router",
    "pipelines_router",
    "proxy_router",
    "quality_router",
    "real_estate_router",
    "reconciliation_router",
    "recorder_router",
    "referrals_router",
    "reports_router",
    "review_router",
    "scraping_api_router",
    "seo_router",
    "sessions_router",
    "share_router",
    "stats_router",
    "structure_router",
    "system_router",
    "templates_api_router",
    "training_router",
    "transform_router",
    "travel_router",
    "untagged_router",
    "vision_router",
    "webhooks_router",
    "x402_router",
]
