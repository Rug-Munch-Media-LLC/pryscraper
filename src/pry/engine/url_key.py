"""Pry — canonical key for comparing result URLs.

Two engines rarely agree on a link's spelling: one returns
``https://www.Example.com/path/``, another ``http://example.com/path`` with
tracking parameters attached. Deduplicating those as separate hits loses the
agreement signal, so they are reduced to one comparable key here.

Stripping scheme and host prefixes is safe for identity; stripping the
tracking parameters is safe because they never change which page is served.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref_", "igshid")
_HOST_PREFIXES = ("www.", "m.", "amp.")


def url_key(url: str) -> str:
    """Return a comparable key for a result URL. Never raises."""
    try:
        parts = urlsplit(url)
    except ValueError:
        logger.debug("unparseable_url", extra={"url": url[:120]})
        return url.strip().lower()
    host = (parts.hostname or "").lower()
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix) :]
            break
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit(("", host, parts.path.rstrip("/") or "/", urlencode(sorted(kept)), ""))


__all__ = ["url_key"]
