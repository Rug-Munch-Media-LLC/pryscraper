"""Pry — Proxy Manager with affiliate-signup flow.
Tries free proxies first (Tor, public rotating). When premium proxy is needed,
prompts user to sign up via affiliate links. Pre-wired to 5+ providers.

Health scoring/circuit-breaker lives in :mod:`pry.engine.proxy_health`
(mixed in via :class:`ProxyHealthMixin`); the provider catalog lives in
:mod:`pry.engine.proxy_providers`. This module keeps configuration,
selection, and the signup/referral flow.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from pry.core.paths import PRY_DATA_DIR
from pry.engine.proxy_health import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    COOLDOWN_SECONDS,
    HEALTH_WINDOW_SIZE,
    ProxyHealthMixin,
)
from pry.engine.proxy_providers import (
    FREE_PROXY_SOURCES,
    PREMIUM_PROXY_PROVIDERS,
    find_provider,
    get_proxy_referral,
    get_proxy_referral_summary,
    get_proxy_referral_url,
    list_proxy_referrals,
    parse_ts as _parse_ts,
)

logger = logging.getLogger(__name__)

PROXY_DIR = PRY_DATA_DIR / "proxies"
PROXY_DIR.mkdir(parents=True, exist_ok=True)

#: Credential files are owner-only: they hold proxy user/pass and API keys.
CREDENTIALS_MODE = 0o600

_URL_USERINFO_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")
_SECRET_KV_RE = re.compile(
    r"(?i)((?:password|passwd|api[_-]?key)\s*[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)"
)

_selection_index = 0
_selection_lock = threading.Lock()


def redact_credentials(text: str) -> str:
    """Mask passwords/API keys in a URL or log/exception string.

    Defensive last line: callers must never interpolate raw config dicts into
    logs, but if one slips through this keeps the secret out of the log line.
    """
    if not text:
        return text
    masked = _URL_USERINFO_RE.sub(r"\1***\3", str(text))
    return _SECRET_KV_RE.sub(r"\1***", masked)


def reset_selection_rotation() -> None:
    """Reset the tie-break rotation used by :meth:`ProxyManager.get_best_proxy`."""
    global _selection_index
    with _selection_lock:
        _selection_index = 0


@dataclass
class ProxyConfig:
    """Proxy configuration.

    ``password`` and ``api_key`` are excluded from ``repr()`` so a stray
    ``logger.debug("%s", config)`` cannot leak them.
    """

    provider: str = "free"
    proxy_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    proxy_type: str = "http"
    geo: str = "auto"
    rotation: str = "per_request"
    auto_rotate: bool = True


class ProxyManager(ProxyHealthMixin):
    """Manages proxy selection, free fallbacks, and premium signup flow."""

    # Tunable health params (per-instance so tests can shrink them).
    health_window_size = HEALTH_WINDOW_SIZE
    consecutive_failure_threshold = CONSECUTIVE_FAILURE_THRESHOLD
    cooldown_seconds = COOLDOWN_SECONDS
    #: How long a per-domain affinity win/failure record stays valid.
    affinity_ttl_seconds = 3600

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or PROXY_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "active_config.json"
        self.creds_file = self.data_dir / "credentials.json"
        self.health_file = self.data_dir / "proxy_health.json"
        self.active_config = self._load_config()
        self.credentials: dict[str, ProxyConfig] = self._load_credentials()
        self._health_data: dict[str, Any] = self._load_health()
        self._harden_file(self.health_file)
        self._health_lock = threading.Lock()
        self.auto_configure_from_env()

    # ── Credential file hygiene ─────────────────────────────────
    def _harden_file(self, path: Path) -> bool:
        """Force ``0600`` on a secret file; refuse it if that cannot be done.

        Returns True when the file is absent or owner-only afterwards. A
        group/world-readable file is chmod'ed on first touch (self-healing);
        if the chmod fails we return False so the caller refuses to load it.
        """
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            return True  # absent -> nothing to protect
        if mode & 0o077 == 0:
            return True
        logger.warning(
            "proxy_secret_permissions_loose",
            extra={"path": str(path), "mode": oct(mode)},
        )
        try:
            os.chmod(path, CREDENTIALS_MODE)
            mode = path.stat().st_mode & 0o777
        except OSError as e:
            logger.error(
                "proxy_secret_permissions_unfixable",
                extra={"path": str(path), "error": redact_credentials(str(e))[:120]},
            )
            return False
        if mode & 0o077:
            logger.error(
                "proxy_secret_permissions_refused",
                extra={"path": str(path), "mode": oct(mode)},
            )
            return False
        return True

    # ── Config / credentials persistence ────────────────────────
    def _load_config(self) -> ProxyConfig:
        if self.config_file.exists():
            if not self._harden_file(self.config_file):
                logger.error("proxy_config_refused_insecure_permissions")
                return ProxyConfig()
            try:
                return ProxyConfig(**json.loads(self.config_file.read_text()))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("proxy_state_load_failed", extra={"error": str(e)[:160]})
        return ProxyConfig()

    def _save_health(self) -> None:
        """Persist health state owner-only: keys are proxy URLs with credentials."""
        super()._save_health()
        try:
            os.chmod(self.health_file, CREDENTIALS_MODE)
        except OSError as e:
            logger.debug("proxy_health_chmod_failed", extra={"error": str(e)[:80]})

    def _load_credentials(self) -> dict[str, ProxyConfig]:
        if self.creds_file.exists():
            if not self._harden_file(self.creds_file):
                logger.error("proxy_credentials_refused_insecure_permissions")
                return {}
            try:
                data = json.loads(self.creds_file.read_text())
                return {k: ProxyConfig(**v) for k, v in data.items()}
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(
                    "proxy_state_load_failed",
                    extra={"error": redact_credentials(str(e))[:160]},
                )
        return {}

    def _write_secret_file(self, path: Path, payload: str) -> None:
        """Write a secrets file owner-only (0600) and re-assert the mode."""
        try:
            path.write_text(payload)
            os.chmod(path, CREDENTIALS_MODE)
            if path.stat().st_mode & 0o077:
                logger.error("proxy_secret_write_not_private", extra={"path": str(path)})
        except OSError as e:
            logger.debug(
                "proxy_secret_write_failed",
                extra={"error": redact_credentials(str(e))[:80]},
            )

    def _save_config(self) -> None:
        self._write_secret_file(self.config_file, json.dumps(self.active_config.__dict__, indent=2))

    def _save_credentials(self) -> None:
        data = {k: v.__dict__ for k, v in self.credentials.items()}
        self._write_secret_file(self.creds_file, json.dumps(data, indent=2, default=str))

    # ── Selection ───────────────────────────────────────────────
    def get_proxy_url(self) -> str | None:
        """Get the healthiest active proxy URL. Returns None if no usable proxy configured.

        Never returns a dead/cooldown proxy: if the only candidate is tripped,
        this returns None so callers fall back to the next tier instead of
        burning the last-resort proxy tier on a known-bad endpoint.
        """
        return self.get_best_proxy()

    def _candidate_proxies(self) -> list[str]:
        """Collect the proxy URLs that are currently selectable.

        Mirrors the historical get_proxy_url() resolution per provider, but as
        a list so health scoring can pick the best one (pool > single URL).
        """
        c = self.active_config
        if c.provider == "webshare":
            pool = self.webshare_pool()
            if pool:
                return pool
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        if c.provider == "free":
            if c.proxy_url and c.proxy_url != "rotating":
                return [c.proxy_url]
            return []
        cred = self.credentials.get(c.provider)
        if not cred:
            return []
        url = self._credential_proxy_url(cred)
        return [url] if url else []

    @staticmethod
    def _credential_proxy_url(cred: ProxyConfig) -> str | None:
        """Resolve a stored credential entry to a concrete proxy URL."""
        if cred.api_key:
            return f"http://{cred.api_key}@proxy.{cred.provider}.com:8000"
        if cred.username and cred.password:
            return f"{cred.proxy_type}://{cred.username}:{cred.password}@{cred.proxy_url}"
        if cred.proxy_url:
            return cred.proxy_url
        return None

    # ── Per-domain affinity / failure accounting (TTL-bounded) ──
    def _affinity_state(self, domain_key: str) -> tuple[dict[str, int], dict[str, float]]:
        affinity: dict[str, int] = self._health_data.setdefault("affinity", {}).setdefault(
            domain_key, {}
        )
        stamps: dict[str, float] = self._health_data.setdefault("affinity_ts", {}).setdefault(
            domain_key, {}
        )
        return affinity, stamps

    def _fresh_affinity(self, domain_key: str) -> dict[str, int]:
        """Affinity wins that are still inside the TTL; expired ones are ignored."""
        affinity, stamps = self._affinity_state(domain_key)
        if not stamps:
            return dict(affinity)  # legacy state written before TTL stamps existed
        now = time.time()
        return {
            proxy: score
            for proxy, score in affinity.items()
            if now - float(stamps.get(proxy, 0.0)) <= self.affinity_ttl_seconds
        }

    def _domain_failures(self, domain_key: str) -> dict[str, int]:
        """Failure counts per proxy for a domain (expired counts are dropped)."""
        failures: dict[str, int] = self._health_data.setdefault("domain_failures", {}).setdefault(
            domain_key, {}
        )
        _, stamps = self._affinity_state(domain_key)
        now = time.time()
        return {
            proxy: count
            for proxy, count in failures.items()
            if now - float(stamps.get(proxy, 0.0)) <= self.affinity_ttl_seconds
        }

    def _record_affinity(self, proxy_url: str, success: bool, domain: str) -> None:
        """Update domain affinity + failure count, resetting stale entries first."""
        domain_key = self._normalize_domain(domain)
        affinity, stamps = self._affinity_state(domain_key)
        now = time.time()
        if now - float(stamps.get(proxy_url, now)) > self.affinity_ttl_seconds:
            affinity[proxy_url] = 0
            self._health_data.setdefault("domain_failures", {}).setdefault(domain_key, {}).pop(
                proxy_url, None
            )
        super()._record_affinity(proxy_url, success, domain)
        stamps[proxy_url] = now
        failures: dict[str, int] = self._health_data.setdefault("domain_failures", {}).setdefault(
            domain_key, {}
        )
        if success:
            failures.pop(proxy_url, None)
        else:
            failures[proxy_url] = failures.get(proxy_url, 0) + 1

    def _rotate_ties(self, healthy: list[str], candidates: list[str]) -> str:
        """Pick the healthiest proxy; equally-scored proxies rotate round-robin.

        The cursor walks the configured pool order, so after a proxy is
        quarantined the next call lands on the following pool member rather
        than an arbitrary remaining tie.
        """
        global _selection_index
        scores = {proxy: self._health_score_of(proxy) for proxy in healthy}
        top = max(scores.values())
        ties = [proxy for proxy in healthy if scores[proxy] == top]
        if len(ties) == 1:
            return ties[0]
        order = {proxy: index for index, proxy in enumerate(candidates)}
        with _selection_lock:
            start = _selection_index % len(candidates)
            _selection_index += 1
            return next((proxy for proxy in ties if order[proxy] >= start), ties[0])

    def get_best_proxy(self, domain: str | None = None) -> str | None:
        """Single entry point: healthiest proxy for ``domain``, or None.

        Quarantine: proxies in circuit-breaker cooldown are skipped, and a
        proxy that repeatedly failed for this specific domain is skipped for
        that domain until its affinity window (``affinity_ttl_seconds``)
        expires — failures are not retried forever.
        """
        candidates = self._candidate_proxies()
        if not candidates:
            return None
        with self._health_lock:
            healthy = [proxy for proxy in candidates if not self._is_in_cooldown(proxy)]
            domain_key = self._normalize_domain(domain) if domain else None
            if domain_key:
                failures = self._domain_failures(domain_key)
                healthy = [
                    proxy
                    for proxy in healthy
                    if failures.get(proxy, 0) < self.consecutive_failure_threshold
                ]
                if not healthy:
                    return None
                affinity = self._fresh_affinity(domain_key)
                winners = [proxy for proxy in healthy if affinity.get(proxy, 0) > 0]
                if winners:
                    return max(
                        winners,
                        key=lambda proxy: (affinity.get(proxy, 0), self._health_score_of(proxy)),
                    )
            if not healthy:
                return None
            return self._rotate_ties(healthy, candidates)

    # ── Signup / referral flow ──────────────────────────────────
    def get_signup_link(self, provider_tag: str = "") -> str:
        """Get the affiliate signup link for a provider. Records the click for revenue tracking."""
        if not provider_tag:
            provider_tag = "brightdata"
        provider = find_provider(provider_tag) or PREMIUM_PROXY_PROVIDERS[0]
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_manager",
                user_id=os.getenv("USER", ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_track_failed", extra={"error": str(e)[:80]})
        return provider["signup_url"]

    def list_providers(self, free: bool = True, premium: bool = True) -> dict[str, Any]:
        """List all available proxy providers."""
        result: dict[str, Any] = {"free": [], "premium": []}
        if free:
            result["free"] = FREE_PROXY_SOURCES
        if premium:
            result["premium"] = PREMIUM_PROXY_PROVIDERS
        result["webshare"] = self.webshare_pool_info()
        return result

    # ── Webshare residential pool (webshare_proxy.py) ─────────────────
    def webshare_pool(self) -> list[str]:
        """Return the cached Webshare residential proxy pool (env or gopass)."""
        from pry.engine.webshare_proxy import load_webshare_proxies

        return load_webshare_proxies()

    def next_webshare_proxy(self) -> str | None:
        """Return the next Webshare proxy (round-robin), or None if the pool is empty."""
        from pry.engine.webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()

    def webshare_pool_info(self) -> dict[str, Any]:
        """Metadata about the Webshare pool, with credentials masked."""
        from pry.engine.webshare_proxy import mask_proxy_url, webshare_source

        pool = self.webshare_pool()
        return {
            "provider": "webshare",
            "source": webshare_source(),
            "count": len(pool),
            "proxies": [mask_proxy_url(p) for p in pool],
        }

    def _public_config(self) -> dict[str, Any]:
        """Active config safe for API responses/logs (secrets masked)."""
        data = dict(self.active_config.__dict__)
        for key in ("password", "api_key"):
            if data.get(key):
                data[key] = "***"
        return data

    def select_provider(self, provider_tag: str, credentials: dict | None = None) -> dict[str, Any]:
        """Select a premium provider. If credentials provided, save them."""
        provider = find_provider(provider_tag)
        if not provider:
            return {"success": False, "error": f"Unknown provider: {provider_tag}"}

        self.get_signup_link(provider_tag)

        if credentials:
            self.credentials[provider_tag] = ProxyConfig(
                provider=provider_tag,
                proxy_url=credentials.get("proxy_url", f"gate.{provider_tag}.com:8000"),
                username=credentials.get("username", ""),
                password=credentials.get("password", ""),
                api_key=credentials.get("api_key", ""),
                proxy_type=credentials.get("proxy_type", "http"),
            )
            self.active_config = self.credentials[provider_tag]
            self._save_credentials()
            self._save_config()
            return {
                "success": True,
                "provider": provider_tag,
                "config": self._public_config(),
            }

        return {
            "success": False,
            "needs_signup": True,
            "signup_url": provider["signup_url"],
            "message": (
                f"Visit {provider['signup_url']} to sign up for {provider['name']}, "
                "then call this endpoint again with credentials."
            ),
            "provider": provider,
        }

    def auto_configure_from_env(self) -> bool:
        """Check environment variables for proxy credentials and auto-configure."""
        # Webshare residential pool: WEBSHARE_PROXY_LIST env takes priority.
        # gopass-only availability stays lazy (on-demand via webshare_pool())
        # so a provisioned secret never surprises the active config.
        if os.getenv("WEBSHARE_PROXY_LIST") and self.webshare_pool():
            self.credentials["webshare"] = ProxyConfig(
                provider="webshare",
                proxy_url="",
                proxy_type="http",
                rotation="pool",
                auto_rotate=True,
            )
            if not self.active_config.provider or self.active_config.provider == "free":
                self.active_config = self.credentials["webshare"]
            self._save_credentials()
            self._save_config()
            return True
        for provider in PREMIUM_PROXY_PROVIDERS:
            tag = provider["tag"]
            env_prefix = f"PRY_PROXY_{tag.upper()}_"
            url = os.getenv(env_prefix + "URL")
            user = os.getenv(env_prefix + "USERNAME")
            pwd = os.getenv(env_prefix + "PASSWORD")
            api_key = os.getenv(env_prefix + "API_KEY")
            if url or (user and pwd) or api_key:
                self.credentials[tag] = ProxyConfig(
                    provider=tag,
                    proxy_url=url or f"gate.{tag}.com:8000",
                    username=user or "",
                    password=pwd or "",
                    api_key=api_key or "",
                )
                if not self.active_config.provider or self.active_config.provider == "free":
                    self.active_config = self.credentials[tag]
                self._save_credentials()
                self._save_config()
                return True
        return False

    def get_recommendation(self, last_error: str = "") -> dict[str, Any]:
        """Get a recommendation for which proxy provider to use.

        Returns: signup URL, estimated cost, why recommended.
        """
        if not self.needs_premium_proxy(last_error):
            return {"needs_premium": False, "message": "Free fallbacks sufficient"}
        provider = PREMIUM_PROXY_PROVIDERS[0]
        return {
            "needs_premium": True,
            "reason": f"Site appears blocked: '{last_error[:80]}'",
            "recommended_provider": provider["name"],
            "signup_url": self.get_signup_link(provider["tag"]),
            "estimated_cost": provider["min_price"],
            "free_trial": provider.get("free_trial", "Unknown"),
            "all_providers": PREMIUM_PROXY_PROVIDERS[:3],
        }

    def record_referral_click(self, provider_tag: str, user_id: str = "") -> str:
        """Record a referral click for a specific provider. Returns the click_id."""
        provider = find_provider(provider_tag)
        if not provider:
            return ""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            return tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_signup",
                user_id=user_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_record_failed", extra={"error": str(e)[:80]})
        return ""

    def get_recent_clicks(self, days_back: int = 30) -> list[dict[str, Any]]:
        """Get recent proxy referral clicks for revenue tracking."""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            cutoff = datetime.now(UTC).timestamp() - (days_back * 86400)
            return [
                c
                for c in tracker.clicks  # type: ignore[attr-defined]  # ReferralTracker.clicks is loaded dynamically from DB
                if c.get("source", "").startswith("proxy")
                and _parse_ts(c.get("timestamp", "")) >= cutoff
            ]
        except Exception as e:  # noqa: BLE001
            logger.debug("recent_clicks_failed", extra={"error": str(e)[:80]})
            return []

    # ── Proxy referral catalog (from proxy_referrals.py) ────────────────
    def get_proxy_referral(self, provider_tag: str) -> dict[str, Any]:
        """Get the curated referral info for a proxy provider (see proxy_providers)."""
        return get_proxy_referral(provider_tag)

    def get_proxy_referral_url(self, provider_tag: str) -> str:
        """Get just the referral URL for a proxy provider."""
        return get_proxy_referral_url(provider_tag)

    def list_proxy_referrals(self) -> list[dict[str, Any]]:
        """List all proxy provider referrals (curated, marketing-friendly view)."""
        return list_proxy_referrals()

    def get_proxy_referral_summary(self) -> dict[str, Any]:
        """Return a per-tier summary of proxy referrals."""
        return get_proxy_referral_summary()
