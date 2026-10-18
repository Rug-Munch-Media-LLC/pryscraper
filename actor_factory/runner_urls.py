"""URL helpers used by the actor runner."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse


def same_domain_links(content: str, base_url: str) -> list[str]:
    """Extract same-domain http(s) links from markdown or HTML content."""
    base = urlparse(base_url)
    found: list[str] = []
    for raw in re.findall(r"\]\((https?://[^)\s]+)|href=[\"'](https?://[^\"']+)", content):
        link = raw[0] or raw[1]
        parsed = urlparse(urljoin(base_url, link))
        if parsed.scheme not in ("http", "https") or parsed.netloc != base.netloc:
            continue
        clean = parsed._replace(fragment="").geturl().rstrip("/")
        if clean and clean != base_url.rstrip("/") and clean not in found:
            found.append(clean)
    return found


def normalize_urls(raw_input: dict[str, Any]) -> list[str]:
    """Accept requestListSources objects or plain strings."""
    raw = raw_input.get("urls") or []
    urls: list[str] = []
    for entry in raw:
        u = entry.get("url") if isinstance(entry, dict) else str(entry)
        if u and u.startswith(("http://", "https://")):
            urls.append(u)
    return urls
