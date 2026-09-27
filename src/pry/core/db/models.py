"""Pry - SQLAlchemy ORM models (facade).

Each model corresponds to a former JSON store (see the docstring on the
top-level ``db`` package for the mapping). This module re-exports the
``DeclarativeBase`` subclass and every live table from focused modules:

- ``models_base``     — Base, _now, _HAS_SA
- ``models_scraping`` — quality/intel/structure/monitors/accounts/reports/pipelines/webhooks
- ``models_auth``     — users, API keys, usage, scrape jobs, audit events
- ``models_billing``  — balances, ledger, hosting, agency, referrals, actors, x402
- ``models_resilience`` — domain_method_stats (durable learned method memory)

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# pyright: basic
from __future__ import annotations

from pry.core.db.models_auth import (
    APIKey,
    AuditEvent,
    ScrapeJob,
    Usage,
    User,
)
from pry.core.db.models_base import _HAS_SA, Base, _now
from pry.core.db.models_billing import (
    Actor,
    Agency,
    Balance,
    HostedInstance,
    HostingInvoice,
    HostingPlan,
    LedgerEntry,
    ReferralClick,
    ReferralConversion,
    ReferralInAppUsage,
    X402PaymentRecord,
    X402SettlementRecord,
)
from pry.core.db.models_resilience import DomainMethodStat
from pry.core.db.models_scraping import (
    Account,
    BrowserSession,
    IntelSnapshot,
    Monitor,
    MonitorRun,
    Pipeline,
    QualityCheck,
    Report,
    StructureSnapshot,
    Webhook,
)

__all__ = [
    "_HAS_SA",
    "APIKey",
    "Account",
    "Actor",
    "Agency",
    "AuditEvent",
    "Balance",
    "Base",
    "BrowserSession",
    "DomainMethodStat",
    "HostedInstance",
    "HostingInvoice",
    "HostingPlan",
    "IntelSnapshot",
    "LedgerEntry",
    "Monitor",
    "MonitorRun",
    "Pipeline",
    "QualityCheck",
    "ReferralClick",
    "ReferralConversion",
    "ReferralInAppUsage",
    "Report",
    "ScrapeJob",
    "StructureSnapshot",
    "Usage",
    "User",
    "Webhook",
    "X402PaymentRecord",
    "X402SettlementRecord",
    "_now",
]
