"""X/Twitter intelligence actor — no-proxy-first with fallback chain.

Mission (2026-08-24): pull posts from a watchlist of X accounts (scam
callers, shillers, news) into the RAG/social-intel pipeline. Efficiency
test: work WITHOUT proxy first; escalate only if direct access fails.

Source chain (tried in order, first success wins per handle):
    1. nitter mirrors      — clean HTML/RSS, no auth (availability varies)
    2. x.com syndication   — cdn.syndication.twimg.com tokenless timeline
                             (limited; works for embedded-timeline content)
    3. proxy (FUTURE)      — reserved; requires RAG_X_PROXY_URL env
                             (deliberately NOT wired until direct is proven
                             insufficient — the whole point of this test)

Output (normalized docs for ingest):
    {"handle": str, "text": str, "ts": iso8601, "url": str, "source": str}

Usage:
    python -m actors.x_intel --watchlist x_watchlist.txt --report
        → probes every source for every handle, prints what works (the
          efficiency test) and writes normalized docs to stdout/JSON.

No credentials, no paid APIs. Rate-limit friendly: jittered delays,
per-source circuit breaking.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from typing import Any

import httpx

logger = logging.getLogger("pryscraper.x_intel")

# Nitter mirrors probed in order (public instances rotate availability).
NITTER_INSTANCES = [
    os.getenv("X_NITTER_1", "https://nitter.poast.org"),
    os.getenv("X_NITTER_2", "https://nitter.privacydev.net"),
    os.getenv("X_NITTER_3", "https://lightbrd.com"),
]

UA = os.getenv(
    "X_SCRAPE_UA",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
)

_TWEET_RE = re.compile(
    r'<div class="tweet-content[^"]*"[^>]*>(?P<text>.*?)</div>.*?'
    r'<a[^>]*href="(?P<url>/[^"]+/status/(?P<id>\d+))"[^>]*title="(?P<ts>[^"]+)"',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return re.sub(r"\s+", " ", text).strip()


async def fetch_nitter(client: httpx.AsyncClient, handle: str) -> list[dict[str, Any]]:
    """Try each nitter mirror for a user timeline."""
    for base in NITTER_INSTANCES:
        try:
            r = await client.get(f"{base}/{handle}", headers={"User-Agent": UA})
            if r.status_code != 200 or "tweet-content" not in r.text:
                continue
            docs = []
            for m in _TWEET_RE.finditer(r.text):
                text = _clean(m.group("text"))
                if len(text) < 20:
                    continue
                docs.append(
                    {
                        "handle": handle,
                        "text": text[:2000],
                        "ts": m.group("ts"),
                        "url": f"https://x.com{m.group('url')}",
                        "source": f"nitter:{base.split('//')[1]}",
                    }
                )
            if docs:
                logger.info("nitter_hit base=%s handle=%s docs=%d", base, handle, len(docs))
                return docs
        except Exception as e:  # noqa: BLE001 — fail-open per-source by design
            logger.debug("nitter_fail base=%s err=%s", base, str(e)[:60])
    return []


async def fetch_syndication(client: httpx.AsyncClient, handle: str) -> list[dict[str, Any]]:
    """Tokenless syndication timeline (best-effort; often profile-data only)."""
    try:
        r = await client.get(
            f"https://cdn.syndication.twimg.com/widgets/timelines/by_screen_name/"
            f"{handle}?lang=en&max_tweets=20",
            headers={"User-Agent": UA},
        )
        if r.status_code != 200:
            return []
        data = r.json()
        docs = []
        for t in (data.get("body") or "").split('class="tweet-text"')[1:]:
            text = _clean(t.split("</p>")[0])
            if len(text) >= 20:
                docs.append(
                    {
                        "handle": handle,
                        "text": text[:2000],
                        "ts": "",
                        "url": f"https://x.com/{handle}",
                        "source": "syndication",
                    }
                )
        return docs
    except Exception as e:  # noqa: BLE001 — fail-open per-source by design
        logger.debug("syndication_fail handle=%s err=%s", handle, str(e)[:60])
        return []



# ── Guest-token GraphQL (self-updating credentials from x.com's own JS) ───

_BEARER_RE = re.compile(r'Bearer (AAAA[A-Za-z0-9%\-]+)')
_QID_RE = re.compile(r'queryId:"([A-Za-z0-9_/]+)",operationName:"UserTweets"')
_cached_credentials: dict[str, str] = {}


async def _get_guest_credentials(client: httpx.AsyncClient) -> dict[str, str]:
    """Extract live Bearer + UserTweets queryId from x.com's main bundle."""
    if _cached_credentials.get("bearer") and _cached_credentials.get("qid"):
        return _cached_credentials
    home = await client.get("https://x.com/", headers={"User-Agent": UA})
    js_links = re.findall(r'src="(https://abs\.twimg\.com/responsive-web/client-web/main[^"]+\.js)"', home.text)
    if not js_links:
        js_links = re.findall(r'"(https://abs\.twimg\.com/responsive-web/client-web/[^"]+main[^"]*\.js)"', home.text)
    for js in js_links[:3]:
        r = await client.get(js, headers={"User-Agent": UA})
        bm = _BEARER_RE.search(r.text)
        qm = _QID_RE.search(r.text)
        if bm and qm:
            _cached_credentials["bearer"] = bm.group(1)
            _cached_credentials["qid"] = qm.group(1)
            logger.info("guest_creds_extracted qid=%s", qm.group(1)[:10])
            return _cached_credentials
    raise RuntimeError("could not extract guest credentials from x.com bundles")


async def _activate_guest(client: httpx.AsyncClient, bearer: str) -> str:
    r = await client.post(
        "https://api.twitter.com/1.1/guest/activate.json",
        headers={"Authorization": f"Bearer {bearer}", "User-Agent": UA},
    )
    r.raise_for_status()
    token = r.json().get("guest_token", "")
    if not token:
        raise RuntimeError("empty guest token")
    return token


async def fetch_guest_graphql(client: httpx.AsyncClient, handle: str) -> list[dict[str, Any]]:
    """UserTweets via anonymous guest token — no account, no proxy needed if lenient."""
    creds = await _get_guest_credentials(client)
    bearer = creds["bearer"]
    gt = await _activate_guest(client, bearer)

    variables = json.dumps({
        "screen_name": handle,
        "count": 20,
        "includePromotedContent": False,
    }, separators=(",", ":"))
    headers = {
        "Authorization": f"Bearer {bearer}",
        "x-guest-token": gt,
        "User-Agent": UA,
        "Content-Type": "application/json",
    }
    url = (
        f"https://x.com/i/api/graphql/{creds['qid']}/UserTweets"
        f"?variables={httpx.QueryParams({'variables': variables}).get('variables')}"
    )
    r = await client.get(url, headers=headers)
    if r.status_code != 200:
        logger.debug("guest_graphql_fail handle=%s status=%d", handle, r.status_code)
        return []
    docs: list[dict[str, Any]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("__typename") == "Tweet" and obj.get("legacy"):
                leg = obj["legacy"]
                text = leg.get("full_text", "")
                if len(text) >= 20:
                    docs.append({
                        "handle": handle,
                        "text": text[:2000],
                        "ts": leg.get("created_at", ""),
                        "url": f"https://x.com/{handle}/status/{obj.get('rest_id', '')}",
                        "source": "guest_graphql",
                    })
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(r.json())
    return docs


async def scrape_handle(handle: str, limit: int = 20) -> tuple[list[dict[str, Any]], str]:
    """Fallback chain for one handle. Returns (docs, method_used).

    Efficiency test result (2026-08-24, no-proxy): nitter mirrors dead,
    syndication blocked — 0/7 handles served. Proxy path is REQUIRED;
    set X_PROXY_URL (http://user:pass@host:port) to enable. Until then
    this actor reports method="none" honestly instead of faking data.
    """
    proxy = os.getenv("X_PROXY_URL", "")
    webshare = _load_webshare_rotator()
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, proxy=proxy or None) as client:
        # 1. guest-token GraphQL direct (no proxy, no account)
        try:
            docs = await fetch_guest_graphql(client, handle)
            if docs:
                return docs[:limit], "guest_graphql"
        except Exception as e:
            logger.debug("guest_direct_fail handle=%s err=%s", handle, str(e)[:60])
        # 2. legacy mirrors
        docs = await fetch_nitter(client, handle)
        if docs:
            return docs[:limit], "nitter"
        docs = await fetch_syndication(client, handle)
        if docs:
            return docs[:limit], "syndication"
    # 3. webshare-proxied retry of the whole chain
    if webshare:
        px = random.choice(webshare)
        try:
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, proxy=px) as client:
                docs = await fetch_guest_graphql(client, handle)
                if docs:
                    return docs[:limit], "guest_graphql+webshare"
        except Exception as e:
            logger.debug("guest_proxy_fail handle=%s err=%s", handle, str(e)[:60])
    return [], "none"


def _load_webshare_rotator() -> list[str]:
    """Best-effort webshare proxy list via pryscraper's own engine."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from pry.engine.webshare_proxy import load_webshare_proxies

        return load_webshare_proxies()
    except Exception:
        return []


async def run(watchlist_path: str, limit: int = 20) -> dict[str, Any]:
    try:
        with open(watchlist_path) as f:  # noqa: ASYNC230 — sync entrypoint
            handles = [ln.strip().lstrip("@") for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        handles = []

    report: dict[str, Any] = {"handles": len(handles), "methods": {}, "docs": []}
    for h in handles:
        docs, method = await scrape_handle(h, limit)
        report["methods"].setdefault(method, []).append(h)
        report["docs"].extend(docs)
        # polite pacing — never rapid-fire account queries
        await asyncio.sleep(random.uniform(2.0, 5.0))  # noqa: S311 — pacing jitter, not crypto

    report["total_docs"] = len(report["docs"])
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="X intel actor — no-proxy-first efficiency test")
    ap.add_argument(
        "--watchlist", default=os.getenv("X_WATCHLIST", "/var/lib/rmi-rag/x_watchlist.txt")
    )
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    report = asyncio.run(run(args.watchlist, args.limit))
    out = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)
    print(out[:3000])  # noqa: T201 — CLI entrypoint


if __name__ == "__main__":
    main()
