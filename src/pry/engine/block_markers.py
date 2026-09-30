"""Marker tables and pure helpers for block detection.

Split from block_detection.py on 2026-08-29 to clear the 200-line structure cap.
Pure data and pure functions only — no behaviour lives here, and the thresholds
that decide what counts as a block are constants here so the classifier below
reads them from one place.

The two gates in this file exist because real, VALID fetches were being discarded:
  _MIN_BODY_MARKERS_FOR_BLOCK  a single incidental marker is not a block. A served
      744 KB article contained "challenge-platform" once and was thrown away.
  _MAX_BLOCK_COPY_BYTES  block pages are small and articles are large. A 313 KB
      article containing the word "forbidden" was thrown away.
"""

from __future__ import annotations

import re

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


_WEAK_CF_MARKERS: frozenset[str] = frozenset({"challenge-platform"})


#: Marker DENSITY gate — applies to the Cloudflare body path ONLY.
#:
#: A real Cloudflare interstitial carries several CF markers together
#: ("just a moment", "cf-chl-", "challenge-platform"), so requiring this many
#: distinct markers is sound evidence. Header evidence (cf-mitigated, cf-ray +
#: 403) is authoritative on its own and is unaffected.
#:
#: Measured 2026-08-29: theblock.co served 744,148 bytes of real article
#: through the premium proxy whose body named "challenge-platform" once, in
#: the script tag Cloudflare injects into every page it serves.
#:
#: This constant is deliberately NOT applied to the CAPTCHA path. A real
#: hCaptcha or Turnstile interstitial typically carries exactly ONE widget
#: marker, so a density rule built on Cloudflare's shape made single-CAPTCHA
#: pages undetectable — it was applied to a differently-shaped threat. The
#: two paths solve different problems, and only the density one over-corrected.
_MIN_BODY_MARKERS_FOR_BLOCK = 2


#: A short page carrying anti-bot copy IS a block page. A large page carrying the
#: same word is an article that happens to contain it. Measured 2026-08-29:
#: immunefi.com served 313,783 bytes through the premium proxy and was rejected
#: because the body contained the word "forbidden" once — an article ABOUT a
#: forbidden topic, not a refusal. Every generic-copy branch below has this shape,
#: the CAPTCHA widget path included: a widget ref only proves the page IS a
#: challenge when the page is small enough to BE the challenge.
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


def _norm_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Lowercase header names so lookups are case-insensitive."""
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}
