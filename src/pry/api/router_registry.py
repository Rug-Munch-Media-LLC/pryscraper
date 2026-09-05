"""Router registry — imports every router and mounts them on the app.

Split out of api.py (god-file split, 2026-09). All ``include_router`` calls
live in :func:`register_routers` so the app factory stays thin.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any

from fastapi import FastAPI

from pry.api.routers.ai.agency import router as agency_router
from pry.api.routers.ai.ai import router as ai_router
from pry.api.routers.ai.analysis import router as analysis_router
from pry.api.routers.commerce.commerce import router as commerce_router
from pry.api.routers.commerce.commerce_data import router as commerce_data_router
from pry.api.routers.commerce.costing import router as costing_router
from pry.api.routers.commerce.dashboard import router as dashboard_router
from pry.api.routers.commerce.marketplace import router as marketplace_router
from pry.api.routers.core.admin import router as admin_router
from pry.api.routers.core.auth import router as auth_router
from pry.api.routers.core.automation import router as automation_router
from pry.api.routers.core.batch import router as batch_router
from pry.api.routers.core.capabilities import router as capabilities_router
from pry.api.routers.core.circuit_breaker import router as circuit_breaker_router
from pry.api.routers.core.config import router as config_router
from pry.api.routers.core.diagnostics import router as diagnostics_router
from pry.api.routers.core.health import router as health_router
from pry.api.routers.data.attention import router as attention_router
from pry.api.routers.data.crypto_market import router as crypto_market_router
from pry.api.routers.data.enrichment import router as enrichment_router
from pry.api.routers.data.healthcare_data import router as healthcare_data_router
from pry.api.routers.data.intelligence import router as intelligence_router
from pry.api.routers.data.jobs import router as jobs_router
from pry.api.routers.data.legal_docs import router as legal_docs_router
from pry.api.routers.data.local_data import router as local_data_router
from pry.api.routers.integrations.alerts import router as alerts_router
from pry.api.routers.integrations.compliance import router as compliance_router
from pry.api.routers.integrations.email import router as email_router
from pry.api.routers.integrations.export import router as export_router
from pry.api.routers.integrations.gdpr import router as gdpr_router
from pry.api.routers.integrations.integrations import router as integrations_router
from pry.api.routers.scraping.advanced import router as advanced_router
from pry.api.routers.scraping.execute import router as execute_router
from pry.api.routers.scraping.extraction import router as extraction_router
from pry.api.routers.scraping.freshness import router as freshness_router
from pry.api.routers.user.crm import router as crm_router

# gov_data / ip_data routers land from parallel agents; import them guarded so
# the app keeps working (and the x402 gates stay armed) before they arrive.
try:
    from pry.api.routers.data.gov_data import router as gov_data_router

    _GOV_DATA_ROUTER: Any | None = gov_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _GOV_DATA_ROUTER = None
try:
    from pry.api.routers.data.ip_data import router as ip_data_router

    _IP_DATA_ROUTER: Any | None = ip_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _IP_DATA_ROUTER = None
# climate_data / research_data routers land in this tree; import them guarded
# so the app keeps working (and the x402 gates stay armed) if they have not
# landed yet.
try:
    from pry.api.routers.data.climate_data import router as climate_data_router

    _CLIMATE_DATA_ROUTER: Any | None = climate_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _CLIMATE_DATA_ROUTER = None
try:
    from pry.api.routers.data.research_data import router as research_data_router

    _RESEARCH_DATA_ROUTER: Any | None = research_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _RESEARCH_DATA_ROUTER = None
# events_data / freight_data / energy_data / food_data / supply_data routers
# land in this tree; import them guarded so the app keeps working (and the
# x402 gates stay armed) if they have not landed yet.
try:
    from pry.api.routers.data.events_data import router as events_data_router

    _EVENTS_DATA_ROUTER: Any | None = events_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _EVENTS_DATA_ROUTER = None
try:
    from pry.api.routers.data.freight_data import router as freight_data_router

    _FREIGHT_DATA_ROUTER: Any | None = freight_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _FREIGHT_DATA_ROUTER = None
try:
    from pry.api.routers.data.energy_data import router as energy_data_router

    _ENERGY_DATA_ROUTER: Any | None = energy_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _ENERGY_DATA_ROUTER = None
try:
    from pry.api.routers.data.food_data import router as food_data_router

    _FOOD_DATA_ROUTER: Any | None = food_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _FOOD_DATA_ROUTER = None
try:
    from pry.api.routers.data.supply_data import router as supply_data_router

    _SUPPLY_DATA_ROUTER: Any | None = supply_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _SUPPLY_DATA_ROUTER = None
# app_store_data / news_data / compliance_data / deals_data routers land in
# this tree from parallel agents; import them guarded so the app keeps working
# (and the x402 gates stay armed) if they have not landed yet.
try:
    from pry.api.routers.data.app_store_data import router as app_store_data_router

    _APP_STORE_DATA_ROUTER: Any | None = app_store_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _APP_STORE_DATA_ROUTER = None
try:
    from pry.api.routers.data.news_data import router as news_data_router

    _NEWS_DATA_ROUTER: Any | None = news_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _NEWS_DATA_ROUTER = None
try:
    from pry.api.routers.integrations.compliance_data import router as compliance_data_router

    _COMPLIANCE_DATA_ROUTER: Any | None = compliance_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _COMPLIANCE_DATA_ROUTER = None
try:
    from pry.api.routers.data.deals_data import router as deals_data_router

    _DEALS_DATA_ROUTER: Any | None = deals_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _DEALS_DATA_ROUTER = None
# bidding_data router lands from a parallel agent; import it guarded so
# the app keeps working (and the x402 gates stay armed) before it arrives.
try:
    from pry.api.routers.data.bidding_data import router as bidding_data_router

    _BIDDING_DATA_ROUTER: Any | None = bidding_data_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _BIDDING_DATA_ROUTER = None
# billing_packs router (bulk scrape-credit crypto checkout) — guarded so
# the app keeps working if the commerce module has not landed yet.
try:
    from pry.api.routers.commerce.billing_packs import router as billing_packs_router

    _BILLING_PACKS_ROUTER: Any | None = billing_packs_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _BILLING_PACKS_ROUTER = None
# billing_subscription router (hosted subscription crypto checkout) — guarded
# so the app keeps working if the commerce module has not landed yet.
try:
    from pry.api.routers.commerce.billing_subscription import (
        router as billing_subscription_router,
    )

    _BILLING_SUBSCRIPTION_ROUTER: Any | None = billing_subscription_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _BILLING_SUBSCRIPTION_ROUTER = None
# hosting router (cloud hosting signup + checkout) — guarded so the app keeps
# working if the commerce.hosting module has not landed yet.
try:
    from pry.api.routers.commerce.hosting import router as hosting_router

    _HOSTING_ROUTER: Any | None = hosting_router
except ImportError:  # pragma: no cover — parallel build not landed yet
    _HOSTING_ROUTER = None
from pry.api.routers.ai.vision import router as vision_router
from pry.api.routers.commerce.reconciliation import router as reconciliation_router
from pry.api.routers.commerce.referrals import router as referrals_router
from pry.api.routers.commerce.reports import router as reports_router
from pry.api.routers.commerce.review import router as review_router
from pry.api.routers.commerce.training import router as training_router
from pry.api.routers.commerce.x402 import router as x402_router
from pry.api.routers.core.api_keys import router as api_keys_router
from pry.api.routers.core.proxy import router as proxy_router
from pry.api.routers.core.quality import router as quality_router
from pry.api.routers.core.sessions import router as sessions_router
from pry.api.routers.core.share import router as share_router
from pry.api.routers.core.signup import router as signup_router
from pry.api.routers.core.stats import router as stats_router
from pry.api.routers.core.system import router as system_router
from pry.api.routers.core.templates import router as templates_router
from pry.api.routers.core.well_known import router as well_known_router
from pry.api.routers.data.real_estate import router as real_estate_router
from pry.api.routers.data.sports_data import router as sports_data_router
from pry.api.routers.data.travel import router as travel_router
from pry.api.routers.integrations.monitoring import router as monitoring_router
from pry.api.routers.integrations.webhooks import router as webhooks_router
from pry.api.routers.scraping.parsing import router as parsing_router
from pry.api.routers.scraping.pipeline import router as pipeline_router
from pry.api.routers.scraping.pipelines import router as pipelines_router
from pry.api.routers.scraping.recorder import router as recorder_router
from pry.api.routers.scraping.scraping import router as scraping_router
from pry.api.routers.scraping.scraping_api import router as scraping_api_router
from pry.api.routers.scraping.seo import router as seo_router
from pry.api.routers.scraping.streams import router as streams_router
from pry.api.routers.scraping.structure import router as structure_router
from pry.api.routers.scraping.transform import router as transform_router
from pry.payments.crypto.router import router as crypto_payment_router


def register_routers(app: FastAPI) -> None:
    """Mount every router on *app* (order preserved from the original api.py)."""
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(healthcare_data_router)
    app.include_router(scraping_router)
    app.include_router(templates_router)
    app.include_router(ai_router)
    app.include_router(admin_router)
    app.include_router(advanced_router)
    app.include_router(agency_router)
    app.include_router(alerts_router)
    app.include_router(analysis_router)
    app.include_router(automation_router)
    app.include_router(batch_router)
    app.include_router(crm_router)
    app.include_router(crypto_market_router)
    app.include_router(circuit_breaker_router)
    app.include_router(commerce_router)
    app.include_router(commerce_data_router)
    app.include_router(compliance_router)
    app.include_router(capabilities_router)
    app.include_router(config_router)
    app.include_router(costing_router)
    app.include_router(dashboard_router)
    app.include_router(diagnostics_router)
    app.include_router(email_router)
    app.include_router(enrichment_router)
    app.include_router(execute_router)
    app.include_router(export_router)
    app.include_router(extraction_router)
    app.include_router(freshness_router)
    app.include_router(attention_router)
    app.include_router(gdpr_router)
    app.include_router(integrations_router)
    app.include_router(intelligence_router)
    app.include_router(jobs_router)
    app.include_router(legal_docs_router)
    app.include_router(local_data_router)
    app.include_router(marketplace_router)
    # gov_data / ip_data routers are included when their modules have landed.
    if _GOV_DATA_ROUTER is not None:
        app.include_router(_GOV_DATA_ROUTER)
    if _IP_DATA_ROUTER is not None:
        app.include_router(_IP_DATA_ROUTER)
    # climate_data / research_data routers are included when they have landed.
    if _CLIMATE_DATA_ROUTER is not None:
        app.include_router(_CLIMATE_DATA_ROUTER)
    if _RESEARCH_DATA_ROUTER is not None:
        app.include_router(_RESEARCH_DATA_ROUTER)
    # events_data / freight_data / energy_data / food_data / supply_data routers
    # are included when they have landed.
    if _EVENTS_DATA_ROUTER is not None:
        app.include_router(_EVENTS_DATA_ROUTER)
    if _FREIGHT_DATA_ROUTER is not None:
        app.include_router(_FREIGHT_DATA_ROUTER)
    if _ENERGY_DATA_ROUTER is not None:
        app.include_router(_ENERGY_DATA_ROUTER)
    if _FOOD_DATA_ROUTER is not None:
        app.include_router(_FOOD_DATA_ROUTER)
    if _SUPPLY_DATA_ROUTER is not None:
        app.include_router(_SUPPLY_DATA_ROUTER)
    # app_store_data / news_data / compliance_data / deals_data routers are
    # included when they have landed.
    if _APP_STORE_DATA_ROUTER is not None:
        app.include_router(_APP_STORE_DATA_ROUTER)
    if _NEWS_DATA_ROUTER is not None:
        app.include_router(_NEWS_DATA_ROUTER)
    if _COMPLIANCE_DATA_ROUTER is not None:
        app.include_router(_COMPLIANCE_DATA_ROUTER)
    if _DEALS_DATA_ROUTER is not None:
        app.include_router(_DEALS_DATA_ROUTER)
    # bidding_data router is included when it has landed.
    if _BIDDING_DATA_ROUTER is not None:
        app.include_router(_BIDDING_DATA_ROUTER)
    # billing_packs router is included when it has landed.
    if _BILLING_PACKS_ROUTER is not None:
        app.include_router(_BILLING_PACKS_ROUTER)
    # billing_subscription router is included when it has landed.
    if _BILLING_SUBSCRIPTION_ROUTER is not None:
        app.include_router(_BILLING_SUBSCRIPTION_ROUTER)
    # hosting router (cloud hosting signup + checkout) is included when it has landed.
    if _HOSTING_ROUTER is not None:
        app.include_router(_HOSTING_ROUTER)
    app.include_router(monitoring_router)
    app.include_router(parsing_router)
    app.include_router(pipeline_router)
    app.include_router(real_estate_router)
    app.include_router(travel_router)
    app.include_router(pipelines_router)
    app.include_router(proxy_router)
    app.include_router(quality_router)
    app.include_router(reconciliation_router)
    app.include_router(recorder_router)
    app.include_router(referrals_router)
    app.include_router(reports_router)
    app.include_router(review_router)
    app.include_router(seo_router)
    app.include_router(scraping_api_router)
    app.include_router(sessions_router)
    app.include_router(share_router)
    app.include_router(signup_router)
    app.include_router(well_known_router)
    app.include_router(sports_data_router)
    app.include_router(stats_router)
    app.include_router(structure_router)
    app.include_router(system_router)
    app.include_router(training_router)
    app.include_router(transform_router)
    app.include_router(streams_router)
    app.include_router(api_keys_router)
    app.include_router(vision_router)
    app.include_router(webhooks_router)
    app.include_router(x402_router)
    app.include_router(crypto_payment_router)
