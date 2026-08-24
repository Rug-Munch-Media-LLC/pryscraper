#!/usr/bin/env python3
"""Live validation: scrape a real URL per template, count fields extracted.

Usage:
  python templates/validate_live.py [--pry-url http://127.0.0.1:8005]
                                   [--max-templates 10]
                                   [--category news]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

TEMPLATES_DIR = Path(__file__).parent

# Test URLs picked for each site — known-good article/product pages.
# Add more as templates are validated.
SITE_TEST_URLS: dict[str, str] = {
    "bbc.com": "https://www.bbc.com/news/articles/c0lz0v3gg41o",
    "nytimes.com": "https://www.nytimes.com/2026/07/01/business/economy.html",
    "cnn.com": "https://www.cnn.com/2026/07/01/politics/index.html",
    "theguardian.com": "https://www.theguardian.com/world/2026/jul/01/test",
    "reuters.com": "https://www.reuters.com/world/",
    "apnews.com": "https://apnews.com/",
    "bloomberg.com": "https://www.bloomberg.com/",
    "forbes.com": "https://www.forbes.com/",
    "businessinsider.com": "https://www.businessinsider.com/",
    "techcrunch.com": "https://techcrunch.com/",
    "theverge.com": "https://www.theverge.com/",
    "arstechnica.com": "https://arstechnica.com/",
    "wired.com": "https://www.wired.com/",
    "axios.com": "https://www.axios.com/",
    "cbsnews.com": "https://www.cbsnews.com/",
    "abcnews.go.com": "https://abcnews.go.com/",
    "aljazeera.com": "https://www.aljazeera.com/",
    "cnet.com": "https://www.cnet.com/",
    "huffpost.com": "https://www.huffpost.com/",
    "foxnews.com": "https://www.foxnews.com/",
    "usatoday.com": "https://www.usatoday.com/",
    "time.com": "https://time.com/",
    "washingtonpost.com": "https://www.washingtonpost.com/",
    "latimes.com": "https://www.latimes.com/",
    "npr.org": "https://www.npr.org/",
    "pbs.org": "https://www.pbs.org/",
    "politico.com": "https://www.politico.com/",
    "vox.com": "https://www.vox.com/",
    "slate.com": "https://slate.com/",
    "vice.com": "https://www.vice.com/",
    # E-commerce
    "amazon.com": "https://www.amazon.com/dp/B08N5WRWNW",
    "ebay.com": "https://www.ebay.com/itm/123456",
    "etsy.com": "https://www.etsy.com/listing/123456",
    "walmart.com": "https://www.walmart.com/ip/123456",
    "target.com": "https://www.target.com/p/-/A-123456",
    "bestbuy.com": "https://www.bestbuy.com/site/sony/1234.p",
    "homedepot.com": "https://www.homedepot.com/p/1234",
    "wayfair.com": "https://www.wayfair.com/furniture/pdp/1234",
    "newegg.com": "https://www.newegg.com/p/1234",
    "shopify.com": "https://www.shopify.com/",
    "aliexpress.com": "https://www.aliexpress.com/item/1234.html",
    "alibaba.com": "https://www.alibaba.com/product-detail/1234.html",
    "asos.com": "https://www.asos.com/us/prd/1234",
    "zara.com": "https://www.zara.com/",
    "hm.com": "https://www.hm.com/",
    "nike.com": "https://www.nike.com/t/1234",
    "adidas.com": "https://www.adidas.com/us/1234",
    "apple.com": "https://www.apple.com/shop/buy-iphone",
    "bhphotovideo.com": "https://www.bhphotovideo.com/c/product/1234-REG/1234",
    "chewy.com": "https://www.chewy.com/dp/1234",
    "rei.com": "https://www.rei.com/product/1234",
    "macys.com": "https://www.macys.com/shop/product/1234",
    "nordstrom.com": "https://www.nordstrom.com/s/1234",
    "sephora.com": "https://www.sephora.com/product/1234",
    "ulta.com": "https://www.ulta.com/p/1234",
    # Travel
    "airbnb.com": "https://www.airbnb.com/rooms/1234",
    "booking.com": "https://www.booking.com/hotel/xx.html",
    "expedia.com": "https://www.expedia.com/h1234",
    "hotels.com": "https://www.hotels.com/ho1234",
    "kayak.com": "https://www.kayak.com/flights",
    "tripadvisor.com": "https://www.tripadvisor.com/",
    # Real estate
    "zillow.com": "https://www.zillow.com/homedetails/1234",
    "realtor.com": "https://www.realtor.com/realestateandhomes-detail/1234",
    "redfin.com": "https://www.redfin.com/zipcode/1234",
}


def template_site(template: dict) -> str:
    site = template.get("site", "")
    for domain in SITE_TEST_URLS:
        if domain in site:
            return domain
    return site


def scrape_via_pry(pry_url: str, url: str, template: dict) -> dict:
    """POST a template-based extraction to /v1/extract (free endpoint).

    /v1/extract is NOT x402-gated and accepts a JSON schema with
    selector -> field name mappings. This is the closest free proxy
    to the template engine.
    """
    schema = template.get("schema", {})
    # Convert template schema to the flatter shape /v1/extract expects
    flat_schema = {}
    for f in schema.get("fields", []):
        name = f.get("name", "")
        sel = f.get("selector", "")
        if name and sel:
            flat_schema[name] = sel
    payload = {
        "url": url,
        "schema": flat_schema,
    }
    api_key = os.environ.get("PRY_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=15) as c:
        r = c.post(f"{pry_url}/v1/extract", json=payload, headers=headers)
        if r.status_code == 402:
            return {"error": "HTTP 402 (x402 paywall — endpoint not actually free)"}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()


def count_extracted_fields(result: dict, template: dict) -> tuple[int, int]:
    """Return (fields_with_values, total_fields)."""
    fields = template.get("schema", {}).get("fields", [])
    data = result.get("data", {}) or result
    extracted = 0
    for f in fields:
        name = f.get("name", "")
        if not name:
            continue
        v = data.get(name)
        if v and ((isinstance(v, str) and v.strip()) or isinstance(v, (list, dict))):
            extracted += 1
    return extracted, len(fields)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pry-url", default="http://127.0.0.1:8005")
    ap.add_argument("--max-templates", type=int, default=0, help="0 means all")
    ap.add_argument("--category", default=None)
    args = ap.parse_args()

    templates = []
    for p in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            if args.category and data.get("category") != args.category:
                continue
            data["_path"] = p.name
            templates.append(data)
        except json.JSONDecodeError:
            continue

    if args.max_templates:
        templates = templates[: args.max_templates]

    results: dict[str, Any] = {
        "total": len(templates),
        "no_test_url": 0,
        "blocked": 0,
        "no_fields_extracted": 0,
        "partial": 0,
        "full": 0,
        "errors": 0,
        "details": [],
    }

    for t in templates:
        site = template_site(t)
        url = SITE_TEST_URLS.get(site)
        if not url:
            results["no_test_url"] += 1
            results["details"].append(
                {"template": t["_path"], "site": site, "status": "no_test_url"}
            )
            continue

        start = time.time()
        try:
            r = scrape_via_pry(args.pry_url, url, t)
            elapsed = time.time() - start
            if "error" in r:
                if "HTTP 403" in r["error"] or "HTTP 429" in r["error"] or "HTTP 503" in r["error"]:
                    results["blocked"] += 1
                    status = "blocked"
                else:
                    results["errors"] += 1
                    status = "error"
                results["details"].append(
                    {
                        "template": t["_path"],
                        "site": site,
                        "status": status,
                        "error": r["error"],
                        "elapsed_s": round(elapsed, 1),
                    }
                )
                continue
            extracted, total = count_extracted_fields(r, t)
            if total == 0:
                results["errors"] += 1
                status = "no_fields_in_template"
            elif extracted == 0:
                results["no_fields_extracted"] += 1
                status = "no_fields_extracted"
            elif extracted == total:
                results["full"] += 1
                status = "full"
            else:
                results["partial"] += 1
                status = f"partial_{extracted}_of_{total}"
            results["details"].append(
                {
                    "template": t["_path"],
                    "site": site,
                    "status": status,
                    "elapsed_s": round(elapsed, 1),
                }
            )
        except Exception as e:  # noqa: BLE001 - live validation must record all failures
            results["errors"] += 1
            results["details"].append(
                {
                    "template": t["_path"],
                    "site": site,
                    "status": "exception",
                    "error": str(e)[:200],
                }
            )

    # Report
    print("\n=== Pry template live validation ===")
    print(f"Pry URL: {args.pry_url}")
    print(f"Templates tested: {results['total']}")
    print(f"  full extraction:        {results['full']}")
    print(f"  partial extraction:     {results['partial']}")
    print(f"  no fields extracted:    {results['no_fields_extracted']}")
    print(f"  blocked (403/429/503):  {results['blocked']}")
    print(f"  errors:                 {results['errors']}")
    print(f"  no test URL configured: {results['no_test_url']}")

    effective = results["full"] + results["partial"]
    total_tested = (
        effective + results["no_fields_extracted"] + results["blocked"] + results["errors"]
    )
    if total_tested > 0:
        success_rate = (results["full"] / total_tested) * 100
        print(f"\nSUCCESS RATE (full only / total tested): {success_rate:.1f}%")
        print(
            f"PARTIAL+ (any field extracted / total tested): {(effective / total_tested) * 100:.1f}%"
        )

    print("\n=== Details (first 20) ===")
    for d in results["details"][:20]:
        print(f"  {d['template']:40s} {d['status']}")

    out_path = TEMPLATES_DIR / "validate_live_report.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nFull report: {out_path}")

    return 0 if results["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
