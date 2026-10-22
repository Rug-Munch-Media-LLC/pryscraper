"""Pry — Ultimate Scraper orchestration (fallback chain + tier scheduling).

Holds the orchestration half of :class:`UltimateScraper`: the public
``scrape()`` entry point, the 15-tier fallback-chain loop, per-tier retry
configs, block-signal escalation, proxy resolution and result shaping. The
concrete tier implementations live in ``pry.engine.tiers`` (mixed in via
``TierMixin``); the per-domain semaphore registry and the tier→breaker
mapping live in ``pry.engine.circuit_breaker``.

Availability flags and optional scraper singletons live on
``pry.engine.ultimate_scraper`` because tests patch them there; they resolve
lazily through :func:`_us_flag` so patches stay effective.
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
import time
from typing import Any, ClassVar

from pry.core.errors import InvalidRequestError
from pry.core.observability import SCRAPE_LATENCY, span
from pry.engine.circuit_breaker import BREAKER_FOR_TIER, domain_semaphore
from pry.engine.domain_key import memory_domain
from pry.engine.reachability_precheck import reachability_verdict
from pry.engine.retry import async_retry
from pry.engine.scraper_premium_first import PremiumFirstMixin
from pry.engine.tier_chain import TierChainMixin
from pry.engine.tier_cost import tier_cost
from pry.engine.tier_health import record as _record_tier_health
from pry.engine.tier_retry_policy import TierRetryPolicyMixin
from pry.engine.tiers import TierMixin
from pry.engine.tiers_base import _us_flag
from pry.engine.url_guard import validate_url

#: Markers in a tier-failure string that mean a Pry dependency was down rather
#: than the target refusing us.
_DEPENDENCY_MARKERS = (
    "browser version",
    "browser_pool",
    "browser_unavailable",
    "executable doesn't exist",
    "dependency",
)


def classify_verdict(
    errors: list[str],
    block_signal: dict[str, Any] | None,
    tiers_available: int,
) -> str:
    """Name WHY a scrape failed, so a caller does not have to infer it.

    The failure payload used to be "; ".join(errors[-5:]) and nothing else, so
    every failure looked identical. Measured on one site: three consecutive
    attempts returned three different signatures
    ("undetected;camoufox;playwright", "premium_proxy;tls_fingerprint",
    "googlebot;archive;google_cache") for the same URL with the same
    reachability, because the late tiers (archive, google_cache) are rate
    limited and fail INTERMITTENTLY. The signature was noise.

    That noise has a real cost, and it was paid: the last tier in the chain is
    premium_proxy, so "the error names premium_proxy" reads as "the proxy is
    broken" and sent people to rotate proxy credentials when the fault was the
    request budget. A verdict removes that inference entirely.

    blocked     the target actively refused us (a block signal was observed)
    exhausted   nothing refused us; we ran out of tiers or wall-clock
    unavailable a dependency Pry needs is down or unusable
    """
    if block_signal is not None and block_signal.get("kind") not in (None, "none"):
        return "blocked"
    if any(marker in err.lower() for err in errors for marker in _DEPENDENCY_MARKERS):
        return "unavailable"
    if tiers_available and len(errors) >= tiers_available:
        # Every tier was attempted and none refused us.
        return "exhausted"
    return "blocked" if not errors else "exhausted"


logger = logging.getLogger(__name__)


class ScrapeOrchestrator(PremiumFirstMixin, TierRetryPolicyMixin, TierChainMixin, TierMixin):
    """Fallback-chain orchestration mixed into :class:`UltimateScraper`.

    Carries the ``scrape()`` / ``_scrape_with_fallbacks()`` loop, the
    per-attempt bookkeeping and result shaping. Tier methods come from
    :class:`~pry.engine.tiers.TierMixin`; the per-tier retry config and
    block-signal escalation from
    :class:`~pry.engine.tier_retry_policy.TierRetryPolicyMixin`; proxy
    resolution and the fallback-chain builder from
    :class:`~pry.engine.tier_chain.TierChainMixin`; the opt-in paid-first rung
    from :class:`~pry.engine.scraper_premium_first.PremiumFirstMixin`.
    """

    USER_AGENTS: ClassVar[list[str]] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    async def scrape(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Scrape any URL with automatic bypass strategy selection.

        Thin public entry: emits the ``scrape.request`` parent span around
        ``_scrape_with_fallbacks``.

        Per-domain concurrency throttle: at most
        ``circuit_breaker.DOMAIN_MAX_CONCURRENCY`` scrapes run against one site
        at once, keyed on the registrable domain (``domain_key.memory_domain``)
        so spelling variants share one cap.
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
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {"status": "error", "url": url, "error": str(e)}

        proxy_url = self._resolve_proxy_url(opts)
        # Memory key for every tier outcome below (record + reorder): the
        # registrable domain, so one site accumulates one set of samples.
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

        # Trusted cheap tiers, then Tor, then the paid proxy, then caches.
        tier_order = self._build_tier_order(proxy_url, premium_first, domain=domain)

        # Promote the domain's proven-best tier and demote/skip failing ones.
        name_to_fn = dict(tier_order)
        ordered_names = registry.reorder_for_domain(domain, [name for name, _ in tier_order])
        tier_order = [(name, name_to_fn[name]) for name in ordered_names]

        i = 0
        # Per-tier deadline + a ladder budget that is the SUM of the deadlines
        # the chain may still spend. The old fixed 45 s cap was shorter than a
        # single Tor attempt, so tiers 9-15 never ran when an early rung was slow.
        per_tier_s, ladder_budget_s = self._ladder_budget(len(tier_order))
        ladder_deadline = time.monotonic() + ladder_budget_s
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

            remaining = ladder_deadline - time.monotonic()
            if remaining <= 0:
                errors.append("ladder_budget_exhausted")
                break
            timeout_s = min(per_tier_s, remaining)
            unavailable = False
            try:
                async with asyncio.timeout(timeout_s):
                    html, latency, unavailable = await self._attempt_tier(
                        tier_name, tier_fn, url, proxy_url, opts
                    )
            except TimeoutError:
                html, latency = None, timeout_s
                errors.append(f"{tier_name}_timeout")
            # A missing dependency is not a tier loss: the tier never ran.
            unavailable = unavailable or self._tier_unavailable(tier_name)

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

            # The single outcome sink: registry + Prometheus + persisted
            # per-(domain, tier) health. Recording here, AFTER block detection,
            # means a blocked page is a loss, not a win.
            self._record_tier_outcome(
                registry,
                breaker_name,
                domain,
                tier_name,
                success,
                latency,
                block_kind=block_kind,
                unavailable=unavailable,
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

        self._record_telemetry(domain, ordered_names, attempts, None, False, scrape_start, errors)
        last_err = errors[-1] if errors else "all_tiers_failed"
        # A fact about the TARGET, collected once and attached to the failure.
        # Absent on success: a target that answers is never prechecked, so no
        # probe can alter a reachable site's tier order.
        target = await reachability_verdict(url)
        result: dict[str, Any] = {
            "status": "error",
            "verdict": classify_verdict(errors, latest_signal, len(ordered_names)),
            "url": url,
            "error": "; ".join(errors[-5:]) if errors else last_err,
            "tiers_attempted": ordered_names,
            "tiers_failed": errors,
            # Tiers the chain deliberately did not try, with the reason: a
            # caller must distinguish "skipped, never won here" from "failed".
            "tiers_skipped": list(self._last_skipped_tiers),
            "content": "",
            "proxy_recommendation": self._recommend_proxy(last_err),
            # blame_tier False means the chain was never exercised against a
            # working site, so these tier failures are not tier evidence.
            "target_reachability": target["reachability"],
            "blame_tier": target["blame_tier"],
        }
        if latest_signal is not None:
            result["block_signal"] = latest_signal
        return result

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

    async def _attempt_tier(
        self,
        tier_name: str,
        tier_fn: Any,
        url: str,
        proxy_url: str | None,
        opts: dict[str, Any],
    ) -> tuple[Any, float, bool]:
        """Run one tier attempt with its retry config + trace span.

        Returns ``(html, latency_seconds, unavailable)``. html is None on any failure.
        ``unavailable`` is True when the failure was a missing dependency (the
        tier never reached the network), so callers can avoid charging that to
        the tier's record.
        ``InvalidRequestError`` (SSRF rejection) is re-raised so the whole
        chain aborts instead of falling through to other tiers that would
        hit the same unsafe target.
        """
        start = time.time()
        unavailable = False
        try:
            retry_cfg = self._RETRY_CONFIGS.get(tier_name, self._DEFAULT_RETRY)
            # Child span per tier attempt — which bypass strategy a target
            # needed and what each cost.
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
            lowered = str(e).lower()
            unavailable = any(marker in lowered for marker in _DEPENDENCY_MARKERS)
        latency = time.time() - start
        return html, latency, unavailable

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
        unavailable: bool = False,
    ) -> None:
        """Feed one tier outcome to the registry + latency metric + health.

        ``block_kind`` lets the learned ranking tell "does not work here" from
        "works but costs 40x more". The persisted health sample is written HERE
        because only this sink knows the post-block-detection ``success``
        predicate; recording ``bool(html)`` earlier counted a WAF block page as
        a win and a missing dependency as a loss.
        """
        _record_tier_health(
            tier_name, domain=domain, won=success, cost_ms=latency * 1000.0, unavailable=unavailable
        )
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
        """Record telemetry + build the success result; None for a non-str body."""
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
