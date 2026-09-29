"""Pry — adaptive block detection and escalation engine.

Self-contained detector that the fallback chain (adaptive retry,
``ultimate_scraper`` tiers) consults to decide when to escalate a request
to stealth, Tor, proxy, or browser-based extraction.

The module is deliberately dependency-free (stdlib only) so any tier can
import it without side effects::

    from pry.engine.block_detection import classify_response, detect_block

    signal = detect_block(html=resp.text, status=resp.status_code,
                          headers=dict(resp.headers))
    if signal.kind != "none":
        logger.warning(
            "blocked: %s (%.2f) -> escalate via %s; evidence=%s",
            signal.kind, signal.confidence,
            signal.recommended_escalation, signal.evidence,
        )

Detected kinds and their recommended escalation:

===============  ============  ======================================
kind             confidence    recommended_escalation (alternatives)
===============  ============  ======================================
``cloudflare``   0.90-0.97     ``"stealth"`` (or ``"tor"``)
``captcha``      0.90-0.95     ``"stealth"`` (or ``"tor"``)
``rate_limited`` 0.90-0.97     ``"backoff"`` (or ``"proxy"``)
``access_denied`` 0.80-0.90    ``"proxy"`` (or ``"tor"``)
``js_required``  0.75-0.90     ``"browser"``
``none``         0.95          ``""`` (no escalation)
===============  ============  ======================================
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Cloudflare challenge / managed challenge markers.
_CF_MARKERS: tuple[str, ...] = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
)

# CAPTCHA widget markers. "verify you are human" is the generic copy used
# by several providers and is a weaker signal than a concrete widget ref.
_CAPTCHA_MARKERS: tuple[str, ...] = (
    "grecaptcha",
    "hcaptcha.com",
    "challenges.cloudflare.com/turnstile",
    "verify you are human",
)

_RATE_LIMIT_BODY_MARKER = "too many requests"
_ACCESS_DENIED_BODY_MARKERS: tuple[str, ...] = ("access denied", "forbidden")
_JS_REQUIRED_MARKER = "enable javascript"

# HTTP statuses treated as generic access denials (403 without CF headers).
_ACCESS_DENIED_STATUSES: frozenset[int] = frozenset({403})

# Headers that pin a response to Cloudflare when present.
_CF_HEADER = "cf-mitigated"
_CF_RAY_HEADER = "cf-ray"


@dataclass(frozen=True, slots=True)
class BlockSignal:
    """Result of block detection for a single response.

    Attributes:
        kind: One of ``"cloudflare"``, ``"captcha"``, ``"rate_limited"``,
            ``"access_denied"``, ``"js_required"``, or ``"none"``.
        confidence: 0.0-1.0 confidence in the classification.
        recommended_escalation: Next fallback strategy to try, e.g.
            ``"stealth"``, ``"backoff"``, ``"proxy"``, ``"tor"``,
            ``"browser"`` — or ``""`` when no escalation is needed.
        evidence: Human-readable markers that triggered the classification.
    """

    kind: str
    confidence: float
    recommended_escalation: str
    evidence: list[str] = field(default_factory=list)


def _norm_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Lowercase header names so lookups are case-insensitive."""
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


#: Markers that a real, fully-served page can legitimately contain. Cloudflare
#: injects its ``challenge-platform`` script into EVERY page it serves, including
#: the successful ones, so its presence is evidence of nothing on its own.
#: Measured 2026-08-29: theblock.co served 744,148 bytes of real article
#: through the premium proxy, _is_valid passed, and the response was then
#: DISCARDED because the body contained this string exactly once. A valid
#: fetch was thrown away over a <script src> tag. These are only evidence in
#: combination with the others.
_WEAK_CF_MARKERS: frozenset[str] = frozenset({"challenge-platform"})


#: A single incidental marker in a large page is not a block. Providers ship
#: their own widget/script names inside the JS bundle of every page they serve,
#: so a fully-served 744 KB article can contain "challenge-platform" and
#: "grecaptcha" once each (measured on theblock.co, 2026-08-29) and be
#: perfectly readable. Real interstitials are SHORT and carry several markers
#: together, so body evidence below is only conclusive once this many distinct
#: markers are present. Header evidence (cf-mitigated, cf-ray + 403) is
#: authoritative and is unaffected by this.
_MIN_BODY_MARKERS_FOR_BLOCK = 2


#: A short page carrying anti-bot copy IS a block page. A large page carrying the
#: same word is an article that happens to contain it. Measured 2026-08-29:
#: immunefi.com served 313,783 bytes through the premium proxy and was rejected
#: because the body contained the word "forbidden" once — an article ABOUT a
#: forbidden topic, not a refusal. Every generic-copy branch below has this shape.
_MAX_BLOCK_COPY_BYTES = 64 * 1024


def _copy_is_block(lower_html: str, phrase: str, original_len: int) -> bool:
    """True when generic block copy is genuinely the page.

    Block pages are small: an interstitial that says "forbidden" IS the response.
    Articles that mention the word are large, and size is a reliable separator
    that does not need a per-phrase allowlist.
    """
    return phrase in lower_html and original_len <= _MAX_BLOCK_COPY_BYTES


def _body_evidence(markers: tuple[str, ...], lower_html: str) -> list[str]:
    """Return evidence strings for each marker found in the body.

    A weak marker on its own is not evidence — see _WEAK_CF_MARKERS. With
    nothing else present the list comes back empty, so a genuinely served page
    is not misreported as blocked, while "just a moment" / "cf-chl-" (the
    interstitial itself) still trigger a block.
    """
    hits = [f"body contains {marker!r}" for marker in markers if marker in lower_html]
    if len(hits) == 1 and f"body contains {next(iter(_WEAK_CF_MARKERS))!r}" == hits[0]:
        return []
    return hits


def _is_scripts_only(html: str) -> bool:
    """True when the page has no visible text but contains script tags."""
    if not html:
        return False
    # Strip <script>...</script> blocks (including their JS content) before
    # checking for visible text, so inline scripts don't count as content.
    no_scripts = re.sub(
        r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    visible = re.sub(r"<[^>]+>", " ", no_scripts)
    if visible.strip():
        return False
    return bool(re.search(r"<\s*script\b", html, re.IGNORECASE))


def detect_block(html: str, status: int, headers: dict[str, str] | None = None) -> BlockSignal:
    """Detect anti-bot blocks from an HTTP response.

    Examines the response body, status code, and headers for known WAF /
    anti-bot markers and returns a :class:`BlockSignal` describing the
    block kind, confidence, recommended escalation, and evidence.

    Args:
        html: The response body (may be empty).
        status: The HTTP status code.
        headers: Response headers (case-insensitive on lookup).

    Returns:
        A :class:`BlockSignal`. ``kind`` is ``"none"`` when no block
        signals were found.
    """
    norm_headers = _norm_headers(headers)
    lower_html = (html or "").lower()
    original_len = len(html or "")

    # 429 is a definitive rate-limit signal — no body inspection needed.
    if status == 429:
        return BlockSignal(
            kind="rate_limited",
            confidence=0.97,
            recommended_escalation="backoff",
            evidence=["http status 429"],
        )

    # Cloudflare: header markers are the strongest signal, then 403+cf-ray,
    # then body markers alone.
    cf_body_hits = _body_evidence(_CF_MARKERS, lower_html)
    if _CF_HEADER in norm_headers:
        return BlockSignal(
            "cloudflare",
            0.97,
            "stealth",
            [f"header {_CF_HEADER}", *cf_body_hits],
        )
    if status in _ACCESS_DENIED_STATUSES and _CF_RAY_HEADER in norm_headers:
        return BlockSignal(
            "cloudflare",
            0.95,
            "stealth",
            [f"header {_CF_RAY_HEADER}", *cf_body_hits],
        )
    if len(cf_body_hits) >= _MIN_BODY_MARKERS_FOR_BLOCK:
        return BlockSignal("cloudflare", 0.90, "stealth", cf_body_hits)

    # CAPTCHA: concrete widget references are stronger than generic copy.
    captcha_hits = _body_evidence(_CAPTCHA_MARKERS, lower_html)
    if len(captcha_hits) >= _MIN_BODY_MARKERS_FOR_BLOCK:
        has_widget_ref = any(
            marker != "verify you are human" for marker in _CAPTCHA_MARKERS if marker in lower_html
        )
        confidence = 0.95 if has_widget_ref else 0.90
        return BlockSignal("captcha", confidence, "stealth", captcha_hits)

    # Rate limit copy rendered as a soft 200 block page.
    if _copy_is_block(lower_html, _RATE_LIMIT_BODY_MARKER, original_len):
        return BlockSignal(
            "rate_limited",
            0.90,
            "backoff",
            [_body_evidence((_RATE_LIMIT_BODY_MARKER,), lower_html)[0]],
        )

    # Access denied: explicit copy, then bare 403 without CF markers,
    # then generic "forbidden" copy (weakest).
    if _copy_is_block(lower_html, "access denied", original_len):
        return BlockSignal(
            "access_denied",
            0.90,
            "proxy",
            ["body contains 'access denied'"],
        )
    if status in _ACCESS_DENIED_STATUSES:
        return BlockSignal(
            "access_denied",
            0.85,
            "proxy",
            [f"http status {status} without cf headers"],
        )
    if _copy_is_block(lower_html, "forbidden", original_len):
        return BlockSignal(
            "access_denied",
            0.80,
            "proxy",
            ["body contains 'forbidden'"],
        )

    # JavaScript-required pages.
    if _JS_REQUIRED_MARKER in lower_html and original_len <= _MAX_BLOCK_COPY_BYTES:
        return BlockSignal(
            "js_required",
            0.90,
            "browser",
            [f"body contains {_JS_REQUIRED_MARKER!r}"],
        )
    if _is_scripts_only(html or ""):
        return BlockSignal(
            "js_required",
            0.75,
            "browser",
            ["empty body, scripts only"],
        )

    # No block signals found.
    return BlockSignal("none", 0.95, "", [])


def classify_response(status: int, html: str, headers: dict[str, str] | None = None) -> BlockSignal:
    """Convenience wrapper for :func:`detect_block` with status-first args.

    Mirrors how a response object presents its fields (status code first),
    so callers can do::

        signal = classify_response(resp.status_code, resp.text, dict(resp.headers))

    Behavior is identical to :func:`detect_block`.
    """
    return detect_block(html=html, status=status, headers=headers)
