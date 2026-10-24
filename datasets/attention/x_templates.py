"""Pry — X (Twitter) URL templates and DOM selectors.

Public SSR pages (``x.com/<handle>``, ``x.com/i/status/<id>``) render the
first timeline page without a login; ``/search`` does not (it redirects to
the onboarding/login flow), so search is the one kind that needs an
authenticated session.

Contract:
    >>> build_url("status", "20")
    'https://x.com/i/status/20'
    >>> normalize_target("profile_timeline", "@jack")
    'jack'

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import re
from urllib.parse import quote

BASE = "https://x.com"

#: kind -> URL template. ``thread`` and ``status`` share a page; the caller
#: decides how much of the conversation to keep.
TEMPLATES: dict[str, str] = {
    "profile_timeline": BASE + "/{target}",
    "status": BASE + "/i/status/{target}",
    "thread": BASE + "/i/status/{target}",
    "search": BASE + "/search?q={target}&f=live",
}

#: Kinds this lane understands.
KINDS: tuple[str, ...] = tuple(TEMPLATES)

# DOM fallbacks (used when a page carries no SSR JSON).
TWEET_SELECTOR = 'article[data-testid="tweet"]'
TEXT_SELECTOR = '[data-testid="tweetText"]'
USER_NAME_SELECTOR = '[data-testid="User-Name"]'
TIME_SELECTOR = "time[datetime]"

#: URL fragments that mean "you must log in" (search, mostly).
LOGIN_MARKERS: tuple[str, ...] = ("/i/jf/onboarding", "/i/flow/login", "mode=login")

_STATUS_ID_RE = re.compile(r"/status(?:es)?/(\d{1,25})")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def normalize_target(kind: str, target: str) -> str:
    """Normalize a handle/status id/query for the given ``kind``."""
    raw = (target or "").strip()
    if kind in ("status", "thread"):
        match = _STATUS_ID_RE.search(raw)
        digits = match.group(1) if match else re.sub(r"\D", "", raw)
        return digits
    if kind == "profile_timeline":
        handle = raw.rsplit("/", 1)[-1].split("?")[0].lstrip("@")
        return handle if _HANDLE_RE.match(handle) else ""
    return raw


def build_url(kind: str, target: str) -> str:
    """Build the page URL for ``kind``/``target`` (target must be normalized)."""
    template = TEMPLATES.get(kind)
    if template is None:
        raise ValueError(f"unknown kind: {kind!r} (expected one of {KINDS})")
    return template.format(target=quote(target, safe=""))
