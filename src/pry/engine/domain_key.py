"""Pry — canonical memory key for a site (registrable domain, eTLD+1).

The adaptive tier memory and the per-domain concurrency throttle were both
keyed on ``urlparse(url).netloc``. That spelling is not a site identity:
``example.com``, ``www.example.com`` and ``example.com:8443`` are three
unrelated buckets, and ``www.blog.example.com`` collides with
``www.shop.example.com`` only by accident of spelling. Two consequences:

* the throttle let a caller bypass ``DOMAIN_MAX_CONCURRENCY`` simply by
  varying the subdomain or port it asked for, and
* the tier memory never accumulated enough samples on any one key to decide
  anything, because the same site kept landing in fresh buckets.

Both sites are keyed here instead. The reduction is deliberately
conservative: a coarser key always merges *more* memory together, never
splits a real site across buckets, so the failure mode is a slightly
over-shared throttle rather than an unbounded one.

Scope: no path/scope suffix is appended. ``/blog`` and ``/shop`` therefore
share the ``example.com`` bucket. That is the conservative direction — the
concurrency cap stays correct, and the tier memory learns one site's overall
tier behaviour rather than re-learning it per section. It is *not* right for
a site whose ``/blog`` and ``/shop`` need different strategies; that would
need a second, scope-qualified lookup and a rule for merging the two records,
which is a two-key selection scheme and is deliberately out of scope here.

Public-suffix handling: the eTLD+1 reduction uses ``tldextract`` (already in
the dependency tree — pinned at 5.3.2 as a transitive dep of ``crawlee`` /
``apify``, and installed in the runtime image, see requirements.docker.lock),
so the full IANA/public-suffix exception list is honoured with no new
dependency. The extractor is constructed with ``suffix_list_urls=()``: the
list is only ever fetched into ``cache_dir`` and never consulted for a
result, and disabling the network fetch removes a startup-time egress
request plus its failure mode.

Never raises. An unparseable or empty input yields ``"unknown"``, matching
the sentinel the previous ``netloc`` keying already used.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import tldextract

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"
_SUB_LABEL_SEP = "/"
_MAX_KEY_LEN = 253

# Host prefixes that are host-name cosmetics, not distinct sites.
_HOST_PREFIXES = ("www.", "m.", "amp.")

# Public-suffix data is a build/lockfile concern, never a runtime network
# call: suffix_list_urls=() disables tldextract's PSL fetch and cache_dir=None
# stops it writing a cache file.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def memory_domain(url_or_host: str) -> str:
    """Return the memory key for ``url_or_host``: its registrable domain.

    Accepts a full URL, a scheme-relative ``//host/path`` reference, or a bare
    host (``example.com`` / ``example.com:8443`` / ``user:pw@host``). Lower-cases,
    drops the port, credentials, userinfo and any leading ``www.`` / ``m.`` /
    ``amp.``, then reduces to the public suffix plus one label (eTLD+1), so
    ``https://WWW.Example.com:8443/blog`` and ``example.com`` both yield
    ``example.com``.

    A host with no known public suffix (``localhost``, an IP, an intranet
    name) cannot be reduced to an eTLD+1. Rather than invent a public-suffix
    exception list, the full lower-cased host is returned unchanged — the
    most conservative key available, and stable across the www/port variants
    that would otherwise split it. Empty or unparseable input returns
    ``"unknown"``.
    """
    raw = (url_or_host or "").strip()
    if not raw:
        return UNKNOWN
    host = _host_of(raw)
    if not host:
        return UNKNOWN
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix) and len(host) > len(prefix):
            host = host[len(prefix) :]
            break
    return _registrable(host)


def _host_of(raw: str) -> str:
    """Return the lower-cased host (no port, no userinfo) of a URL or host."""
    try:
        host = urlsplit(raw if "//" in raw else f"//{raw}").hostname
    except ValueError:
        logger.debug("unparseable_domain", extra={"host": raw[:120]})
        return ""
    return (host or "").lower().rstrip(".")


def _registrable(host: str) -> str:
    """Reduce ``host`` to eTLD+1, or return it unchanged when not reducible."""
    if len(host) > _MAX_KEY_LEN:
        # Hosts cannot exceed 253 chars; a longer "host" is not a host.
        logger.debug("oversized_domain_key", extra={"len": len(host)})
        return UNKNOWN
    try:
        split = _extract(host)
        key = split.top_domain_under_public_suffix or host
    except ValueError:
        # tldextract raises on an invalid domain name (e.g. empty labels).
        logger.debug("unreducible_domain", extra={"host": host[:120]})
        return host
    for part in (key or "").split(_SUB_LABEL_SEP):
        if not part or _SUB_LABEL_SEP in part:
            return host
    return key or host


__all__ = ["UNKNOWN", "memory_domain"]
