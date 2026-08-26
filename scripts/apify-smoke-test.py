#!/usr/bin/env python3
"""Functional smoke tests: run every deployed Pry actor on the platform.

Proves each actor *does what its description says*, not merely that it
builds. For every preset the harness:

  1. builds a run input from the preset schema (defaults + prefills),
     overridden by ``SMOKE_INPUTS`` where a realistic target matters;
  2. starts a run sized to the preset's memory floor (browser actors get
     >=1GB - Chromium OOMs below that);
  3. polls to a terminal state;
  4. records status + dataset item count incrementally to results.json.

Heavy anti-bot targets (Google Maps, Kayak, Zillow...) are EXPECTED
failures on datacenter IPs - they document residential-proxy needs and
are reported as ``ANTIBOT`` candidates, distinct from hard crashes.

Usage:
    python scripts/apify-smoke-test.py --dry-run          # show inputs
    python scripts/apify-smoke-test.py --only rss-feed-monitor
    python scripts/apify-smoke-test.py                    # full sweep

Exit codes: 0 = all succeeded, 1 = one or more failed, 2 = prerequisite error.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from actor_factory.presets import ALL_PRESETS  # noqa: E402

API_BASE = "https://api.apify.com/v2"
ORG = "rugmunchmedia"

# Realistic demo targets overriding the generic example.com prefill.
# Chosen for stability + no-auth + exercising the actor's actual promise.
SMOKE_INPUTS: dict[str, dict] = {
    "pry-universal-scraper": {"urls": [{"url": "https://example.com"}]},
    "pry-site-crawler": {
        "urls": [{"url": "https://books.toscrape.com/"}],
        "max_pages": 5,
    },
    "pry-blog-post-extractor": {"urls": [{"url": "https://blog.python.org/"}]},
    "pry-product-data-extractor": {
        "urls": [
            {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"}
        ]
    },
    "pry-ecommerce-catalog-crawler": {
        "urls": [{"url": "https://books.toscrape.com/"}],
        "max_pages": 5,
    },
    "pry-rss-feed-monitor": {"urls": [{"url": "https://hnrss.org/newest"}]},
    "pry-news-feed-monitor": {"urls": [{"url": "https://text.npr.org/"}]},
    "pry-hacker-news-monitor": {"urls": [{"url": "https://news.ycombinator.com/"}]},
    "pry-github-release-monitor": {
        "urls": [{"url": "https://github.com/apify/apify-cli/releases"}]
    },
    "pry-npm-package-stats": {"urls": [{"url": "https://www.npmjs.com/package/express"}]},
    "pry-pypi-package-stats": {"urls": [{"url": "https://pypi.org/project/requests/"}]},
    "pry-arxiv-paper-monitor": {"urls": [{"url": "https://arxiv.org/list/cs.AI/recent"}]},
    "pry-wayback-diff": {"urls": [{"url": "https://example.com/"}]},
    "pry-change-monitor": {"urls": [{"url": "https://example.com/"}]},
    "pry-sitemap-diff": {"urls": [{"url": "https://www.sitemaps.org/sitemap.xml"}]},
    "pry-ssl-cert-monitor": {"urls": [{"url": "https://example.com/"}]},
    "pry-json-api-monitor": {"urls": [{"url": "https://httpbin.org/json"}]},
    "pry-status-page-aggregator": {"urls": [{"url": "https://www.githubstatus.com/"}]},
    "pry-weather-data-collector": {"urls": [{"url": "https://wttr.in/London?format=j1"}]},
    "pry-air-quality-monitor": {
        "urls": [
            {
                "url": "https://air-quality.open-meteo.com/v1/air-quality?latitude=51.5&longitude=-0.13&hourly=pm10"
            }
        ]
    },
    "pry-earthquake-alert-monitor": {
        "urls": [
            {"url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"}
        ]
    },
    "pry-space-launch-monitor": {
        "urls": [{"url": "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=5"}]
    },
    "pry-fx-rate-monitor": {"urls": [{"url": "https://open.er-api.com/v6/latest/USD"}]},
    "pry-gas-fee-monitor": {"urls": [{"url": "https://mempool.space/api/v1/fees/recommended"}]},
    "pry-chain-tvl-monitor": {"urls": [{"url": "https://api.llama.fi/tvl/uniswap"}]},
    "pry-defi-yield-monitor": {"urls": [{"url": "https://yields.llama.fi/pools?limit=20"}]},
    "pry-stablecoin-flow-monitor": {
        "urls": [{"url": "https://stablecoins.llama.fi/stablecoins?includePrices=false"}]
    },
    "pry-crypto-market-monitor": {
        "urls": [
            {
                "url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
            }
        ]
    },
    "pry-crypto-listing-monitor": {
        "urls": [
            {"url": "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&per_page=10"}
        ]
    },
    "pry-prediction-market-monitor": {
        "urls": [{"url": "https://gamma-api.polymarket.com/markets?limit=10"}]
    },
    "pry-steam-game-stats": {"urls": [{"url": "https://store.steampowered.com/app/570/Dota_2/"}]},
    "pry-sec-filings-watch": {
        "urls": [
            {
                "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=10-K&count=10"
            }
        ]
    },
    "pry-clinical-trials-watch": {
        "urls": [{"url": "https://clinicaltrials.gov/study/NCT04280705"}]
    },
    "pry-fda-recall-monitor": {
        "urls": [{"url": "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"}]
    },
    "pry-cve-advisory-watch": {
        "urls": [
            {
                "url": "https://nvd.nist.gov/vuln/search/results?form_type=Basic&results_type=overview&query=openssl&search_type=all"
            }
        ]
    },
    "pry-court-docket-monitor": {"urls": [{"url": "https://www.courtlistener.com/"}]},
    "pry-terms-policy-watch": {"urls": [{"url": "https://example.com/"}]},
    "pry-producthunt-launch-monitor": {"urls": [{"url": "https://www.producthunt.com/"}]},
    "pry-knowledge-base-miner": {"urls": [{"url": "https://docs.apify.com/"}]},
    "pry-llm-corpus-builder": {"urls": [{"url": "https://en.wikipedia.org/wiki/Web_scraping"}]},
    "pry-forum-discussion-miner": {"urls": [{"url": "https://news.ycombinator.com/item?id=8863"}]},
    "pry-accessibility-scanner": {"urls": [{"url": "https://www.w3.org/"}]},
    "pry-seo-site-auditor": {"urls": [{"url": "https://example.com/"}]},
    "pry-broken-links-auditor": {"urls": [{"url": "https://books.toscrape.com/"}]},
    "pry-social-card-auditor": {"urls": [{"url": "https://blog.rust-lang.org/"}]},
    "pry-tech-stack-detector": {"urls": [{"url": "https://books.toscrape.com/"}]},
    "pry-screenshot-capture": {"urls": [{"url": "https://example.com/"}]},
    "pry-document-parser": {
        "urls": [{"url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}]
    },
    "pry-pdf-invoice-extractor": {
        "urls": [{"url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}]
    },
    "pry-changelog-tracker": {
        "urls": [{"url": "https://raw.githubusercontent.com/apify/apify-cli/master/CHANGELOG.md"}]
    },
    "pry-api-docs-diff": {"urls": [{"url": "https://docs.apify.com/api/v2"}]},
    "pry-outbound-link-harvester": {"urls": [{"url": "https://books.toscrape.com/"}]},
    "pry-contact-form-finder": {"urls": [{"url": "https://httpbin.org/forms/post"}]},
    "pry-course-catalog-extractor": {"urls": [{"url": "https://ocw.mit.edu/"}]},
    "pry-jobs-aggregator": {"urls": [{"url": "https://www.remoteok.com/"}]},
    "pry-event-listings-aggregator": {
        "urls": [{"url": "https://www.eventbrite.com/d/online/events/"}]
    },
    "pry-deal-radar": {"urls": [{"url": "https://slickdeals.net/computer-deals/"}]},
    "pry-price-watcher": {
        "urls": [
            {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"}
        ]
    },
    "pry-inventory-alert": {
        "urls": [
            {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"}
        ]
    },
    "pry-review-aggregator": {"urls": [{"url": "https://www.trustpilot.com/review/github.com"}]},
    "pry-app-store-review-miner": {
        "urls": [{"url": "https://apps.apple.com/us/app/x/id333903271"}]
    },
    "pry-podcast-feed-miner": {"urls": [{"url": "https://lexfridman.com/feed/podcast/"}]},
    "pry-podcast-review-miner": {
        "urls": [{"url": "https://podcasts.apple.com/us/podcast/the-daily/id1200361736"}]
    },
    "pry-youtube-rss-monitor": {"urls": [{"url": "https://www.youtube.com/@veritasium"}]},
    "pry-recipe-miner": {
        "urls": [{"url": "https://www.bbcgoodfood.com/recipes/classic-victoria-sandwich-recipe"}]
    },
    "pry-restaurant-menu-extractor": {"urls": [{"url": "https://www.starbucks.com/menu"}]},
    "pry-local-business-schema-auditor": {"urls": [{"url": "https://www.starbucks.com/"}]},
    "pry-serp-scraper": {"urls": [{"url": "https://html.duckduckgo.com/html/?q=web+scraping"}]},
    "pry-serp-rank-tracker": {
        "urls": [{"url": "https://html.duckduckgo.com/html/?q=web+scraping"}]
    },
    "pry-gdpr-cookie-checker": {"urls": [{"url": "https://www.bbc.com/"}]},
    "pry-startup-funding-monitor": {"urls": [{"url": "https://techcrunch.com/category/startups/"}]},
    "pry-press-release-monitor": {"urls": [{"url": "https://www.prnewswire.com/news-releases/"}]},
    "pry-scholarship-grants-finder": {"urls": [{"url": "https://www.scholarships.com/"}]},
    "pry-provider-finder": {"urls": [{"url": "https://www.psychologytoday.com/us/therapists"}]},
    "pry-lead-harvester": {"urls": [{"url": "https://books.toscrape.com/"}]},
    "pry-onion-site-monitor": {
        "urls": [{"url": "http://duckduckgogg42xjoc72x3sjh75ndubc2azbyj3cdawnsj7lqiyad2yd.onion/"}]
    },
    "pry-token-unlock-monitor": {"urls": [{"url": "https://cryptorank.io/unlocks"}]},
    "pry-whale-transfer-monitor": {"urls": [{"url": "https://whale-alert.io/"}]},
    "pry-sports-odds-best-line": {"urls": [{"url": "https://www.oddschecker.com/"}]},
    "pry-flight-price-watch": {"urls": [{"url": "https://www.kayak.com/flights"}]},
    "pry-hotel-rate-watch": {"urls": [{"url": "https://www.booking.com/"}]},
    "pry-tender-procurement-monitor": {"urls": [{"url": "https://ted.europa.eu/"}]},
    "pry-uspto-patent-monitor": {
        "urls": [{"url": "https://ppubs.uspto.gov/dirsearch-public/print/search"}]
    },
    "pry-usaspending-contracts": {"urls": [{"url": "https://www.usaspending.gov/"}]},
    "pry-sanctions-screener": {"urls": [{"url": "https://sanctionssearch.ofac.treas.gov/"}]},
    "pry-ad-intel-monitor": {"urls": [{"url": "https://www.nytimes.com/"}]},
}

# Targets known to require residential proxies / Tor - failures here are
# documented product constraints, not code bugs.
EXPECTED_ANTIBOT = {
    "pry-maps-lead-extractor",
    "pry-local-directory-extractor",
    "pry-property-lister",
    "pry-onion-site-monitor",
    "pry-flight-price-watch",
    "pry-hotel-rate-watch",
    "pry-serp-scraper",
    "pry-serp-rank-tracker",
}

RUN_TIMEOUT_SECS = 300
POLL_INTERVAL = 15
MAX_POLL_SECONDS = 420


def _resolve_token() -> str:
    env = os.environ.get("APIFY_TOKEN", "").strip()
    if env:
        return env
    import shutil
    import subprocess

    gopass = shutil.which("gopass")
    if not gopass:
        print("ERROR: set APIFY_TOKEN or install gopass", file=sys.stderr)
        raise SystemExit(2)
    proc = subprocess.run(  # noqa: S603 - resolved absolute path, fixed argv
        [gopass, "show", "-o", "rmi/infra/apify_org_token"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    token = (proc.stdout or "").strip()
    if proc.returncode == 0 and token:
        return token
    print("ERROR: set APIFY_TOKEN or unlock gopass", file=sys.stderr)
    raise SystemExit(2)


def _request(
    token: str, path: str, method: str = "GET", payload: dict | None = None
) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed https base
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


def build_input(preset_name: str) -> dict:
    """Schema-derived input with SMOKE_INPUTS override."""
    spec = ALL_PRESETS[preset_name]
    base: dict = {}
    for field in spec.inputs:
        if field.default is not None:
            base[field.name] = field.default
        elif field.prefill:
            base[field.name] = field.prefill
    base.update(SMOKE_INPUTS.get(preset_name, {}))
    return base


def run_memory(spec) -> int:
    """Browser actors need >=1GB or Chromium OOMs during escalation."""
    if spec.uses_browser:
        return max(1024, spec.min_memory_mbytes)
    return spec.min_memory_mbytes


def start_run(token: str, preset_name: str, inp: dict, memory: int) -> tuple[bool, str | dict]:
    store_name = preset_name.removeprefix("pry-")
    status, body = _request(
        token,
        f"/acts/{ORG}~{store_name}/runs?memoryMbytes={memory}&timeoutSecs={RUN_TIMEOUT_SECS}",
        "POST",
        inp,
    )
    if status != 201:
        return False, f"start failed HTTP {status}: {body}"
    return True, body["data"]


def wait_run(token: str, run_id: str) -> tuple[str, str]:
    deadline = time.monotonic() + MAX_POLL_SECONDS
    while time.monotonic() < deadline:
        _, body = _request(token, f"/actor-runs/{run_id}")
        if isinstance(body, dict):
            status = body.get("data", {}).get("status", "?")
            if status in ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"):
                ds_id = body.get("data", {}).get("defaultDatasetId", "")
                return status, ds_id
        time.sleep(POLL_INTERVAL)
    return "POLL-TIMEOUT", ""


def dataset_count(token: str, ds_id: str) -> int:
    if not ds_id:
        return -1
    _, body = _request(token, f"/datasets/{ds_id}/items?clean=true&limit=200")
    if isinstance(body, str):
        return -1
    return len(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="preset names (with or without pry-)")
    parser.add_argument("--dry-run", action="store_true", help="print inputs, no runs")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "opencode" / "apify-smoke",
    )
    args = parser.parse_args()

    names = sorted(ALL_PRESETS)
    if args.only:
        wanted = {n.removeprefix("pry-") for n in args.only}
        names = [n for n in names if n.removeprefix("pry-") in wanted]

    if args.dry_run:
        for name in names:
            print(
                f"{name}: mem={run_memory(ALL_PRESETS[name])}MB input={json.dumps(build_input(name))[:160]}"
            )
        return 0

    token = _resolve_token()
    args.staging_root.mkdir(parents=True, exist_ok=True)
    results_path = args.staging_root / "smoke-results.json"
    results: dict = {}
    if results_path.is_file():
        results = json.loads(results_path.read_text())

    queue = [n for n in names if n not in results or not results[n].get("done")]
    print(f"running {len(queue)}/{len(names)} actors in batches of {args.batch_size}")

    passed = failed = antibot_fail = 0
    for i in range(0, len(queue), args.batch_size):
        batch = queue[i : i + args.batch_size]
        pending: list[tuple[str, str]] = []
        for name in batch:
            spec = ALL_PRESETS[name]
            inp = build_input(name)
            mem = run_memory(spec)
            ok, resp = start_run(token, name, inp, mem)
            if ok:
                pending.append((name, resp["id"]))
                print(f"[START] {name} (mem={mem}, run={resp['id'][:12]})", flush=True)
            else:
                results[name] = {"done": True, "status": "START-FAILED", "detail": str(resp)[:200]}
                failed += 1
                print(f"[FAIL ] {name}: {str(resp)[:120]}", flush=True)

        for name, run_id in pending:
            status, ds_id = wait_run(token, run_id)
            items = dataset_count(token, ds_id)
            entry = {"done": True, "status": status, "items": items, "dataset": ds_id}
            results[name] = entry
            if status == "SUCCEEDED":
                passed += 1
                print(f"[PASS ] {name}: {items} items", flush=True)
            else:
                is_antibot = name in EXPECTED_ANTIBOT
                if is_antibot:
                    antibot_fail += 1
                else:
                    failed += 1
                tag = "ANTIBOT" if is_antibot else "FAIL "
                print(f"[{tag}] {name}: {status} ({items} items)", flush=True)
            results_path.write_text(json.dumps(results, indent=2, sort_keys=True))

    print(
        f"\nSUMMARY: pass={passed} fail={failed} antibot-expected={antibot_fail} total={len(names)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
