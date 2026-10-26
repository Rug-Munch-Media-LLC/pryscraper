"""X profile timeline via the public syndication endpoint (no auth).

Surface: ``https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>``
Verified from Talos 2026-10-25: HTTP 200, ~370 KB ``text/html``, plain UA, no
cookie. Repeated calls inside ~2 minutes return HTTP 429 (see
``docs/X-SCRAPE-METHOD.md``).
"""

from __future__ import annotations

import re

import httpx

from pry.actors.x_envelope import envelope, refusal
from pry.actors.x_parse import normalize_tweets

SOURCE = "syndication.timeline"
URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def fetch_profile_timeline(
    handle: str,
    *,
    client: httpx.Client | None = None,
    limit: int = 20,
    timeout: float = 25.0,
) -> dict:
    """Fetch one handle's recent tweets, or an honest refusal envelope.

    ``client`` is a DI seam: tests pass a stub and CI never touches the network.
    """
    handle = (handle or "").lstrip("@").strip()
    if not HANDLE_RE.match(handle):
        return refusal(SOURCE, "no_data", detail="invalid handle")

    owns_client = client is None
    client = client or httpx.Client(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    try:
        response = client.get(URL.format(handle=handle))
    except httpx.HTTPError as exc:  # transport failure, never a fabricated payload
        return refusal(SOURCE, "blocked.challenge", detail=f"transport: {type(exc).__name__}")
    finally:
        if owns_client:
            client.close()

    status = response.status_code
    if status == 429:
        return refusal(SOURCE, "blocked.ratelimit", http_status=429)
    if status in (401, 403):
        return refusal(SOURCE, "blocked.auth", http_status=status)
    if status == 404:
        return refusal(SOURCE, "no_data", http_status=404, detail="handle not found")
    if status != 200:
        return refusal(SOURCE, "no_data", http_status=status)

    tweets = normalize_tweets(response.text, handle, limit=limit)
    if not tweets:
        return refusal(
            SOURCE,
            "no_data",
            http_status=200,
            detail="no tweet objects in __NEXT_DATA__ (login wall or JS-only shell)",
        )
    return envelope(
        ok=True,
        source=SOURCE,
        http_status=200,
        data={
            "handle": handle,
            "profile_url": f"https://x.com/{handle}",
            "count": len(tweets),
            "tweets": tweets,
        },
    )
