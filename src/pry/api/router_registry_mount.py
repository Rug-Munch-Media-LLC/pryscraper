"""Router mount tables, split out of router_registry.py on 2026-08-30.

The registry carried one 118-line register_routers() of bare include_router calls,
pushing it 38 lines past its shrink-only baseline. Split by mount ORDER rather than
category, because order is the load-bearing property here: the mount sequence
determines route precedence.

Routers are supplied by the registry as a NAMESPACE mapping rather than as 88
keyword arguments. Two reasons: re-stating the table inside router_registry.py
would defeat the split, and importing them here would be a circular import that
resolves differently depending on which module loads first. Passing globals() is
explicit about the coupling instead of hiding it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Mapping

    from fastapi import FastAPI


def mount_primary(app: FastAPI, ns: Mapping[str, Any]) -> None:
    """First 46 routers, in the registry's original mount order."""
    app.include_router(ns["auth_router"])
    app.include_router(ns["health_router"])
    app.include_router(ns["healthcare_data_router"])
    app.include_router(ns["scraping_router"])
    app.include_router(ns["templates_router"])
    app.include_router(ns["ai_router"])
    app.include_router(ns["admin_router"])
    app.include_router(ns["advanced_router"])
    app.include_router(ns["agency_router"])
    app.include_router(ns["alerts_router"])
    app.include_router(ns["analysis_router"])
    app.include_router(ns["automation_router"])
    app.include_router(ns["batch_router"])
    app.include_router(ns["account_router"])
    app.include_router(ns["crm_router"])
    app.include_router(ns["crypto_market_router"])
    app.include_router(ns["circuit_breaker_router"])
    app.include_router(ns["commerce_router"])
    app.include_router(ns["commerce_data_router"])
    app.include_router(ns["compliance_router"])
    app.include_router(ns["capabilities_router"])
    app.include_router(ns["config_router"])
    app.include_router(ns["costing_router"])
    app.include_router(ns["dashboard_router"])
    app.include_router(ns["diagnostics_router"])
    app.include_router(ns["email_router"])
    app.include_router(ns["enrichment_router"])
    app.include_router(ns["execute_router"])
    app.include_router(ns["export_router"])
    app.include_router(ns["extraction_router"])
    app.include_router(ns["freshness_router"])
    app.include_router(ns["attention_router"])
    app.include_router(ns["gdpr_router"])
    app.include_router(ns["integrations_router"])
    app.include_router(ns["intelligence_router"])
    app.include_router(ns["jobs_router"])
    app.include_router(ns["legal_docs_router"])
    app.include_router(ns["local_data_router"])
    app.include_router(ns["marketplace_router"])
    # gov_data / ip_data routers are included when their modules have landed.
    if ns["_GOV_DATA_ROUTER"] is not None:
        app.include_router(ns["_GOV_DATA_ROUTER"])
    if ns["_IP_DATA_ROUTER"] is not None:
        app.include_router(ns["_IP_DATA_ROUTER"])
    # climate_data / research_data routers are included when they have landed.
    if ns["_CLIMATE_DATA_ROUTER"] is not None:
        app.include_router(ns["_CLIMATE_DATA_ROUTER"])
    if ns["_RESEARCH_DATA_ROUTER"] is not None:
        app.include_router(ns["_RESEARCH_DATA_ROUTER"])
    # events_data / freight_data / energy_data / food_data / supply_data routers
    # are included when they have landed.
    if ns["_EVENTS_DATA_ROUTER"] is not None:
        app.include_router(ns["_EVENTS_DATA_ROUTER"])
    if ns["_FREIGHT_DATA_ROUTER"] is not None:
        app.include_router(ns["_FREIGHT_DATA_ROUTER"])
    if ns["_ENERGY_DATA_ROUTER"] is not None:
        app.include_router(ns["_ENERGY_DATA_ROUTER"])


def mount_secondary(app: FastAPI, ns: Mapping[str, Any]) -> None:
    """Remaining 42 routers, continuing the same order."""
    if ns["_FOOD_DATA_ROUTER"] is not None:
        app.include_router(ns["_FOOD_DATA_ROUTER"])
    if ns["_SUPPLY_DATA_ROUTER"] is not None:
        app.include_router(ns["_SUPPLY_DATA_ROUTER"])
    # app_store_data / news_data / compliance_data / deals_data routers are
    # included when they have landed.
    if ns["_APP_STORE_DATA_ROUTER"] is not None:
        app.include_router(ns["_APP_STORE_DATA_ROUTER"])
    if ns["_NEWS_DATA_ROUTER"] is not None:
        app.include_router(ns["_NEWS_DATA_ROUTER"])
    if ns["_COMPLIANCE_DATA_ROUTER"] is not None:
        app.include_router(ns["_COMPLIANCE_DATA_ROUTER"])
    if ns["_DEALS_DATA_ROUTER"] is not None:
        app.include_router(ns["_DEALS_DATA_ROUTER"])
    # bidding_data router is included when it has landed.
    if ns["_BIDDING_DATA_ROUTER"] is not None:
        app.include_router(ns["_BIDDING_DATA_ROUTER"])
    # billing_packs router is included when it has landed.
    if ns["_BILLING_PACKS_ROUTER"] is not None:
        app.include_router(ns["_BILLING_PACKS_ROUTER"])
    # billing_subscription router is included when it has landed.
    if ns["_BILLING_SUBSCRIPTION_ROUTER"] is not None:
        app.include_router(ns["_BILLING_SUBSCRIPTION_ROUTER"])
    # hosting router (cloud hosting signup + checkout) is included when it has landed.
    if ns["_HOSTING_ROUTER"] is not None:
        app.include_router(ns["_HOSTING_ROUTER"])
    app.include_router(ns["monitoring_router"])
    app.include_router(ns["parsing_router"])
    app.include_router(ns["pipeline_router"])
    app.include_router(ns["real_estate_router"])
    app.include_router(ns["travel_router"])
    app.include_router(ns["pipelines_router"])
    app.include_router(ns["proxy_router"])
    app.include_router(ns["quality_router"])
    app.include_router(ns["reconciliation_router"])
    app.include_router(ns["recorder_router"])
    app.include_router(ns["referrals_router"])
    app.include_router(ns["reports_router"])
    app.include_router(ns["review_router"])
    app.include_router(ns["seo_router"])
    app.include_router(ns["scraping_api_router"])
    app.include_router(ns["sessions_router"])
    app.include_router(ns["share_router"])
    app.include_router(ns["signup_router"])
    app.include_router(ns["well_known_router"])
    app.include_router(ns["sports_data_router"])
    app.include_router(ns["stats_router"])
    app.include_router(ns["analytics_router"])
    app.include_router(ns["structure_router"])
    app.include_router(ns["system_router"])
    app.include_router(ns["training_router"])
    app.include_router(ns["transform_router"])
    app.include_router(ns["streams_router"])
    app.include_router(ns["api_keys_router"])
    app.include_router(ns["vision_router"])
    app.include_router(ns["webhooks_router"])
    app.include_router(ns["x402_router"])
    app.include_router(ns["crypto_payment_router"])
