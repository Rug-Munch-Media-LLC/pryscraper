"""Pry — Referral click tracking, conversion, and revenue helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from db import ReferralClick, ReferralConversion, ReferralInAppUsage, session_scope
from referrals.catalog import PROVIDER_CATALOG

logger = logging.getLogger(__name__)


class ReferralTracker:
    """Track referral clicks, conversions, and revenue."""

    def __init__(self) -> None:
        pass

    def record_click(
        self, provider_tag: str, url: str, source: str = "pry", user_id: str = ""
    ) -> str:
        """Record a referral link click. Returns the tracking ID."""
        click_id = uuid.uuid4().hex[:12]
        try:
            with session_scope() as s:
                s.add(
                    ReferralClick(
                        click_id=click_id,
                        provider=provider_tag,
                        url=url,
                        source=source,
                        user_id=user_id,
                        converted=False,
                        conversion_value_usd=0.0,
                    )
                )
        except SQLAlchemyError as e:
            logger.error(
                "referral_click_failed",
                extra={"click_id": click_id, "provider": provider_tag, "error": str(e)[:200]},
            )
            raise
        logger.info("referral_click", extra={"provider": provider_tag, "source": source})
        return click_id

    def record_conversion(self, click_id: str, revenue_usd: float = 0.0, notes: str = "") -> bool:
        """Record a conversion for a click. Returns True if successful."""
        try:
            with session_scope() as s:
                click = s.query(ReferralClick).filter_by(click_id=click_id).first()
                if click is None:
                    logger.warning(
                        "referral_conversion_click_not_found",
                        extra={"click_id": click_id},
                    )
                    return False
                click.converted = True  # type: ignore[assignment]  # SQLAlchemy Column[bool] → bool
                click.conversion_value_usd = revenue_usd  # type: ignore[assignment]  # SQLAlchemy Column[float] → float
                s.add(
                    ReferralConversion(
                        click_id=click_id,
                        provider=click.provider,
                        revenue_usd=revenue_usd,
                        notes=notes,
                    )
                )
        except SQLAlchemyError as e:
            logger.error(
                "referral_conversion_failed",
                extra={"click_id": click_id, "error": str(e)[:200]},
            )
            raise
        logger.info(
            "referral_conversion",
            extra={"click_id": click_id, "revenue_usd": revenue_usd},
        )
        return True

    def get_catalog(self, category: str = "") -> list[dict[str, Any]]:
        """Get the provider catalog, optionally filtered by category."""
        if category:
            return PROVIDER_CATALOG.get(category, [])
        return [
            {"category": cat, "providers": providers} for cat, providers in PROVIDER_CATALOG.items()
        ]

    def get_stats(self, days_back: int = 30) -> dict[str, Any]:
        """Get referral statistics for the last N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days_back)
        try:
            with session_scope() as s:
                total_clicks = (
                    s.query(func.count(ReferralClick.id))
                    .filter(ReferralClick.ts >= cutoff)
                    .scalar()
                    or 0
                )

                click_rows = (
                    s.query(
                        ReferralClick.provider,
                        func.count(ReferralClick.id).label("cnt"),
                    )
                    .filter(ReferralClick.ts >= cutoff)
                    .group_by(ReferralClick.provider)
                    .all()
                )
                clicks_by_provider = {r.provider: r.cnt for r in click_rows}

                conv_rows = (
                    s.query(
                        ReferralConversion.provider,
                        func.count(ReferralConversion.id).label("cnt"),
                        func.sum(ReferralConversion.revenue_usd).label("rev"),
                    )
                    .filter(ReferralConversion.ts >= cutoff)
                    .group_by(ReferralConversion.provider)
                    .all()
                )
                conversions_by_provider = {r.provider: r.cnt for r in conv_rows}
                revenue_by_provider = {r.provider: float(r.rev or 0.0) for r in conv_rows}

                total_conversions = sum(conversions_by_provider.values())
                total_revenue = sum(revenue_by_provider.values())

                return {
                    "period_days": days_back,
                    "total_clicks": total_clicks,
                    "total_conversions": total_conversions,
                    "clicks_by_provider": clicks_by_provider,
                    "conversions_by_provider": conversions_by_provider,
                    "revenue_by_provider_usd": revenue_by_provider,
                    "total_revenue_usd": total_revenue,
                    "conversion_rate": total_conversions / max(total_clicks, 1),
                    "catalog_size": sum(len(v) for v in PROVIDER_CATALOG.values()),
                }
        except SQLAlchemyError as e:
            logger.error(
                "referral_stats_failed",
                extra={"error": str(e)[:200]},
            )
            raise

    def track_in_app_usage(self, provider_tag: str, revenue_usd: float) -> None:
        """Track revenue from in-app LLM provider usage (per-call)."""
        try:
            with session_scope() as s:
                s.add(
                    ReferralInAppUsage(
                        provider=provider_tag,
                        revenue_usd=revenue_usd,
                    )
                )
        except SQLAlchemyError as e:
            logger.error(
                "referral_in_app_usage_failed",
                extra={"provider": provider_tag, "error": str(e)[:200]},
            )
            raise
        logger.info(
            "referral_in_app_usage",
            extra={"provider": provider_tag, "revenue_usd": revenue_usd},
        )


__all__ = ["ReferralTracker"]
