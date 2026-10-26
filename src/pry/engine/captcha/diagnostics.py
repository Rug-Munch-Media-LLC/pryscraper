"""Pry — CAPTCHA ladder diagnostics.

``captcha_diagnostics()`` is the single truthful answer to "what can run right
now?": the derived tier order, each rung's capability and availability, and the
retired paid providers (with their reason) so nobody proposes one again.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from pry.core.settings import settings
from pry.engine.captcha import probes
from pry.engine.captcha.flaresolverr import LOOPBACK_FALLBACKS
from pry.engine.captcha.registry import REGISTRY
from pry.engine.captcha.tiers import RETIRED_PROVIDERS, ordered_tiers


def captcha_diagnostics() -> dict[str, object]:
    """Return the tier table, live availability and the retirement ledger."""
    rows = [
        {
            "tier": t.tier,
            "kind": t.kind,
            "label": t.label,
            "rank": t.rank,
            "capability": t.capability,
            "available": probes.available(t.capability),
            "missing": t.missing,
        }
        for t in ordered_tiers()
    ]
    return {
        "enabled": bool(settings.captcha_enabled),
        "order": [t.tier for t in ordered_tiers()],
        "tiers": rows,
        "registered_providers": sorted(REGISTRY),
        "retired_providers": [{"name": n, "reason": r} for n, r in RETIRED_PROVIDERS],
        "flaresolverr_url": settings.flaresolverr_url,
        "flaresolverr_fallbacks": list(LOOPBACK_FALLBACKS),
        "max_seconds": settings.captcha_max_seconds,
    }
