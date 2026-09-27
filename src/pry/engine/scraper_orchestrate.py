"""Pry — Ultimate Scraper orchestration (fallback chain + tier scheduling).

Holds the orchestration half of :class:`UltimateScraper`: the public
``scrape()`` entry point, the 15-tier fallback-chain loop, per-tier retry
configs, block-signal escalation, proxy resolution and result shaping. The
concrete tier implementations live in ``pry.engine.tiers`` (mixed in via
``TierMixin``); the per-domain semaphore registry and the tier→breaker
mapping live in ``pry.engine.circuit_breaker``.

Availability flags and the optional scraper singletons (``_has_ai_visual``,
``_mobile_scraper``, ...) remain module-level globals on
``pry.engine.ultimate_scraper`` because tests patch them there; tier-13/15
availability and the resilience ``registry`` are resolved lazily through
:func:`_us_flag` so patches stay effective.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, ClassVar

from pry.core.errors import InvalidRequestError
from pry.core.observability import SCRAPE_LATENCY, span
from pry.engine.circuit_breaker import BREAKER_FOR_TIER, domain_semaphore
from pry.engine.domain_key import memory_domain
from pry.engine.retry import async_retry
from pry.engine.scraper_premium_first import PremiumFirstMixin
from pry.engine.tier_cost import tier_cost
from pry.engine.tier_retry_policy import TierRetryPolicyMixin
from pry.engine.tiers import TierMixin
from pry.engine.tiers_base import _us_flag
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)


class ScrapeOrchestrator(PremiumFirstMixin, TierRetryPolicyMixin, TierMixin):
    """Fallback-chain orchestration mixed into :class:`UltimateScraper`.

    Carries the adaptive tier-order builder and the ``scrape()`` /
    ``_scrape_with_fallbacks()`` loop. Tier methods come from
    :class:`~pry.engine.tiers.TierMixin`; the per-tier retry config and
    block-signal escalation come from
    :class:`~pry.engine.tier_retry_policy.TierRetryPolicyMixin`; the opt-in
    paid-first rung comes from
    :class:`~pry.engine.scraper_premium_first.PremiumFirstMixin`.
    """

    USER_AGENTS: ClassVar[list[str]] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    async def scrape(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Scrape any URL with automatic bypass strategy selection.

        Thin public entry: emits the ``scrape.request`` parent span (with
        final method/success attributes) around ``_scrape_with_fallbacks``,
        which tries up to 10 strategies until one succeeds.

        Per-domain concurrency throttle: at most
        ``circuit_breaker.DOMAIN_MAX_CONCURRENCY`` scrapes may run against the
        same site at once. This prevents a single caller (or a burst of
        callers) from hammering one target site with unbounded parallel
        requests — an abuse vector that would get the target (and our egress
        IPs) rate-limited or banned. Different sites proceed in parallel;
        only same-site concurrency is bounded.

        Keyed on the registrable domain (``domain_key.memory_domain``), not
        the raw netloc: ``www.example.com`` and ``example.com:8443`` are one
        site and must share one cap, or the limit is bypassed by spelling.
        """
        domain = memory_domain(url)
        sem = domain_semaphore(domain)
        async with sem:
            with span("scrape.request", {"http.url": url}) as request_span:
                result = await self._scrape_with_fallbacks(url, options)
                if request_span is not None and isinstance(result, dict):
                    request_span.set_attribute("pry.method", str(result.get("method", "")))
                    request_span.set_attribute("pry.success", result.get("status") == "success")
                    if isinstance(result.get("attempts"), list):
                        request_span.set_attribute("pry.attempts", len(result["attempts"]))
                return result

    async def _scrape_with_fallbacks(
        self, url: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Fallback-chain implementation (tier order, block detection, retries)."""
        opts = options or {}
        errors: list[str] = []
        try:
            validate_url(url)
        except InvalidRequestError as e:
            return {"status": "error", "url": url, "error": str(e)}

        proxy_url = self._resolve_proxy_url(opts)
        # Memory key for every tier outcome below (record + reorder). Registrable
        # domain, so samples accumulate on one site instead of one netloc
        # spelling — see domain_key.memory_domain.
        domain = memory_domain(url)
        scrape_start = time.time()
        attempts: list[dict[str, Any]] = []
        latest_signal: dict[str, Any] | None = None
        # Resolved before the premium attempt so that rung is learnable too.
        registry = _us_flag("registry")

        # Tier 0: Premium proxy — only first if the caller explicitly asks.
        # Default is False: paid proxy is a LAST resort, tried after Tor.
        premium_first = opts.get("use_premium_proxy_first", False)
        if proxy_url and premium_first:
            premium_result, latest_signal = await self._premium_first(
                url=url,
                proxy_url=proxy_url,
                opts=opts,
                domain=domain,
                scrape_start=scrape_start,
                attempts=attempts,
                errors=errors,
                latest_signal=latest_signal,
                registry=registry,
            )
            if premium_result is not None:
                return premium_result

        # Trusted cheap tiers first, then Tor (anonymous, free), then the
        # paid premium proxy LAST, then cached-version fallbacks as the
        # absolute last resort.
        tier_order = self._build_tier_order(proxy_url, premium_first)

        # Adaptive ordering: promote the domain's proven-best tier to the
        # front and demote/skip tiers that have been failing recently. Each
        # domain gets an intelligent, self-improving fallback chain.
        name_to_fn = dict(tier_order)
        ordered_names = registry.reorder_for_domain(domain, [name for name, _ in tier_order])
        tier_order = [(name, name_to_fn[name]) for name in ordered_names]

        i = 0
        try:
            async with asyncio.timeout(45):
                while i < len(tier_order):
                    tier_name, tier_fn = tier_order[i]
                    # Skip external tiers whose circuit breaker is open.
                    breaker_name = BREAKER_FOR_TIER.get(tier_name)
                    if breaker_name and not registry.is_service_allowed(breaker_name):
                        logger.debug(
                            "tier_skipped_circuit_open", extra={"tier": tier_name, "domain": domain}
                        )
                        errors.append(f"{tier_name}: circuit_open")
                        i += 1
                        continue

                    html, latency = await self._attempt_tier(
                        tier_name, tier_fn, url, proxy_url, opts
                    )

                    # Block detection: classify the tier response (or failure) so the
                    # next tier choice can escalate intelligently. Tiers expose only the
                    # body, so status/headers default to 200/{} — body markers drive the
                    # classification. A block page is not content: even if it passes
                    # _is_valid (e.g. a long WAF challenge), it does not count as success
                    # and the chain escalates to the preferred tier family.
                    signal = self._detect_block_signal(html)
                    success = bool(html and self._is_valid(html))
                    block_kind = ""
                    if signal is not None and signal.kind != "none":
                        latest_signal = self._signal_to_dict(signal)
                        self._promote_preferred_tiers(tier_order, i, signal.kind)
                        success = False
                        block_kind = signal.kind

                    self._record_tier_outcome(
                        registry,
                        breaker_name,
                        domain,
                        tier_name,
                        success,
                        latency,
                        block_kind=block_kind,
                    )

                    if success:
                        success_result = self._record_tier_success(
                            domain=domain,
                            tier_name=tier_name,
                            ordered_names=ordered_names,
                            attempts=attempts,
                            scrape_start=scrape_start,
                            errors=errors,
                            html=html,
                            latency=latency,
                            latest_signal=latest_signal,
                            url=url,
                        )
                        if success_result is None:
                            continue
                        return success_result
                    errors.append(f"{tier_name}_failed")
                    attempts.append(
                        {
                            "tier": tier_name,
                            "success": False,
                            "error": f"{tier_name}_failed",
                            "duration_ms": round(latency * 1000, 2),
                        }
                    )
                    i += 1
        except TimeoutError:
            errors.append("timeout_45s")

        self._record_telemetry(domain, ordered_names, attempts, None, False, scrape_start, errors)
        last_err = errors[-1] if errors else "all_tiers_failed"
        result: dict[str, Any] = {
            "status": "error",
            "url": url,
            "error": "; ".join(errors[-5:]) if errors else last_err,
            "content": "",
            "proxy_recommendation": self._recommend_proxy(last_err),
        }
        if latest_signal is not None:
            result["block_signal"] = latest_signal
        return result

    def _resolve_proxy_url(self, opts: dict[str, Any]) -> str | None:
        """Resolve the configured proxy URL from options, ProxyManager, or env."""
        if opts.get("proxy_url"):
            return opts["proxy_url"]
        if opts.get("proxy") is False:
            return None
        try:
            from pry.engine.proxy_manager import ProxyManager

            pm = ProxyManager()
            return pm.get_proxy_url()
        except Exception as e:  # noqa: BLE001
            logger.debug("proxy_resolve_failed", extra={"error": str(e)[:80]})
        env_url = os.getenv("PRY_PROXY_URL") or os.getenv("PROXY_URL")
        return env_url or None

    def _recommend_proxy(self, last_error: str) -> dict[str, Any] | None:
        """Build a proxy recommendation for the response when scraping fails."""
        try:
            from pry.engine.proxy_manager import ProxyManager

            return ProxyManager().get_recommendation(last_error)
        except Exception as e:  # noqa: BLE001
            logger.debug("proxy_recommend_failed", extra={"error": str(e)[:80]})
            return None

    def _result(
        self,
        url: str,
        html: str,
        method: str,
        block_signal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "ok",
            "url": url,
            "raw_html": html,
            "method": method,
            "content": self._extract_text(html),
        }
        if block_signal is not None:
            result["block_signal"] = block_signal
        return result

    def _build_tier_order(
        self, proxy_url: str | None, premium_first: bool
    ) -> list[tuple[str, Any]]:
        """Build the fallback chain (cheap tiers -> Tor -> premium -> cached).

        Note: ``_tier_premium_proxy`` has signature (url, proxy_url, opts)
        while other tiers use (url, opts, proxy_url) — handled at the call
        site in :meth:`_attempt_tier`.
        """
        tier_order: list[tuple[str, Any]] = [
            ("direct", self._tier_direct),
            ("tls_fingerprint", self._tier_tls_fingerprint),
            ("cloudscraper", self._tier_cloudscraper),
            ("flaresolverr", self._tier_flaresolverr),
            ("undetected", self._tier_undetected),
            ("camoufox", self._tier_camoufox),
            ("playwright", self._tier_playwright),
            ("googlebot", self._tier_googlebot),
            # Tor mid-chain: anonymous fallback tried before we pay for a
            # premium proxy, but after the trusted cheap methods.
            ("tor", self._tier_tor),
        ]

        # Premium proxy — the LAST paid resort, after Tor. Only added when it
        # was not already tried first above.
        if proxy_url and not premium_first:
            tier_order.append(("premium_proxy", self._tier_premium_proxy))

        tier_order.extend(
            [
                ("archive", self._tier_archive),
                ("google_cache", self._tier_google_cache),
            ]
        )

        # Tier 13: AI Visual Scraper (screenshot + LLM vision)
        ai_visual = _us_flag("_ai_visual")
        if _us_flag("_has_ai_visual") and ai_visual and ai_visual.is_available():
            tier_order.append(("ai_visual", self._tier_ai_visual))

        # Tier 14: Mobile App API Scraper
        if _us_flag("_has_mobile") and _us_flag("_mobile_scraper"):
            tier_order.append(("mobile_app", self._tier_mobile_app))

        # Tier 15: GraphQL API Discovery
        if _us_flag("_has_graphql") and _us_flag("_graphql_scraper"):
            tier_order.append(("graphql", self._tier_graphql))

        return tier_order

    async def _attempt_tier(
        self,
        tier_name: str,
        tier_fn: Any,
        url: str,
        proxy_url: str | None,
        opts: dict[str, Any],
    ) -> tuple[Any, float]:
        """Run one tier attempt with its retry config + trace span.

        Returns ``(html, latency_seconds)`` — html is None on any failure.
        ``InvalidRequestError`` (SSRF rejection) is re-raised so the whole
        chain aborts instead of falling through to other tiers that would
        hit the same unsafe target.
        """
        start = time.time()
        try:
            retry_cfg = self._RETRY_CONFIGS.get(tier_name, self._DEFAULT_RETRY)
            # Child span per tier attempt — the trace shows exactly which
            # bypass strategies a target needed and what each cost.
            with span("scrape.tier", {"pry.tier": tier_name, "http.url": url}):
                if tier_name == "premium_proxy":
                    html = await async_retry(tier_fn, url, proxy_url, opts, config=retry_cfg)
                else:
                    html = await async_retry(
                        tier_fn, url, opts, proxy_url=proxy_url, config=retry_cfg
                    )
        except InvalidRequestError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.debug("tier_exception", extra={"tier": tier_name, "error": str(e)[:200]})
            html = None
        latency = time.time() - start
        return html, latency

    def _record_tier_outcome(
        self,
        registry: Any,
        breaker_name: str | None,
        domain: str,
        tier_name: str,
        success: bool,
        latency: float,
        *,
        block_kind: str = "",
    ) -> None:
        """Feed one tier outcome to the registry + latency metric.

        ``block_kind`` and the tier's marginal cost are recorded alongside
        the success flag so the learned ranking can tell "this method does
        not work here" from "this method works but costs 40x more", and can
        remember what the wall actually looked like.
        """
        registry.record_domain_tier_result(
            domain,
            tier_name,
            success,
            latency,
            cost_usd=tier_cost(tier_name),
            block_kind=block_kind,
        )
        if breaker_name:
            registry.record_service_result(breaker_name, success)
        if SCRAPE_LATENCY:
            SCRAPE_LATENCY.labels(method=tier_name).observe(latency)

    def _record_tier_success(
        self,
        *,
        domain: str,
        tier_name: str,
        ordered_names: list[str],
        attempts: list[dict[str, Any]],
        scrape_start: float,
        errors: list[str],
        html: Any,
        latency: float,
        latest_signal: dict[str, Any] | None,
        url: str,
    ) -> dict[str, Any] | None:
        """Record telemetry + build the success result.

        Returns None when html isn't a str (defensive — caller continues).
        """
        if not isinstance(html, str):
            return None
        attempts.append(
            {
                "tier": tier_name,
                "success": True,
                "error": None,
                "duration_ms": round(latency * 1000, 2),
            }
        )
        self._record_telemetry(
            domain, ordered_names, attempts, tier_name, True, scrape_start, errors
        )
        return self._result(url, html, tier_name, block_signal=latest_signal)
