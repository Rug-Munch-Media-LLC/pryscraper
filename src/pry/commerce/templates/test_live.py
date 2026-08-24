#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Live template verification script — run on Talos with network access."""

import asyncio
import sys

import httpx

TEMPLATES = [
    ("abcnews-article", "abcnews.go.com", "news"),
    ("adidas-product", "adidas.com", "ecommerce"),
    ("airbnb-listing", "airbnb.com", "travel"),
    ("aliexpress-product", "aliexpress.com", "ecommerce"),
    ("aljazeera-article", "aljazeera.com", "news"),
    ("amazon-product", "amazon.com", "ecommerce"),
    ("amazon-search", "amazon.com", "ecommerce"),
    ("arstechnica-article", "arstechnica.com", "news"),
    ("asos-product", "asos.com", "ecommerce"),
    ("associated-press-article", "apnews.com", "news"),
    ("axios-article", "axios.com", "news"),
    ("bbc-article", "bbc.com", "news"),
    ("bestbuy-product", "bestbuy.com", "ecommerce"),
    ("bhphotovideo-product", "bhphotovideo.com", "ecommerce"),
    ("bloomberg-article", "bloomberg.com", "news"),
    ("booking-hotel", "booking.com", "travel"),
    ("businessinsider-article", "businessinsider.com", "news"),
    ("cbsnews-article", "cbsnews.com", "news"),
    ("chewy-product", "chewy.com", "ecommerce"),
    ("cnet-article", "cnet.com", "news"),
    ("cnn-article", "cnn.com", "news"),
    ("coinmarketcap-coin", "coinmarketcap.com", "financial"),
    ("costco-product", "costco.com", "ecommerce"),
    ("craigslist-listing", "craigslist.org", "classifieds"),
    ("crate-and-barrel-product", "crateandbarrel.com", "ecommerce"),
    ("crunchbase-company", "crunchbase.com", "business"),
    ("cvs-product", "cvs.com", "ecommerce"),
    ("dailymail-article", "dailymail.co.uk", "news"),
    ("dicks-sporting-goods", "dickssportinggoods.com", "ecommerce"),
    ("dw-article", "dw.com", "news"),
    ("ebay-listing", "ebay.com", "ecommerce"),
    ("economist-article", "economist.com", "news"),
    ("espn-sports", "espn.com", "sports"),
    ("etsy-product", "etsy.com", "ecommerce"),
    ("facebook-marketplace", "facebook.com", "classifieds"),
    ("financialtimes-article", "ft.com", "news"),
    ("forbes-article", "forbes.com", "news"),
    ("foxnews-article", "foxnews.com", "news"),
    ("france24-article", "france24.com", "news"),
    ("g2-product", "g2.com", "reviews"),
    ("gap-product", "gap.com", "ecommerce"),
    ("generic-product", "generic", "ecommerce"),
    ("github-repo", "github.com", "development"),
    ("glassdoor-job", "glassdoor.com", "professional"),
    ("google-maps-place", "google.com/maps", "local"),
    ("google-patent", "patents.google.com", "reference"),
    ("h-and-m-product", "hm.com", "ecommerce"),
    ("hackernews-post", "news.ycombinator.com", "news"),
    ("homedepot-product", "homedepot.com", "ecommerce"),
    ("ikea-product", "ikea.com", "ecommerce"),
    ("imdb-movie", "imdb.com", "media"),
    ("indeed-job", "indeed.com", "professional"),
    ("jcpenney-product", "jcpenney.com", "ecommerce"),
    ("kohls-product", "kohls.com", "ecommerce"),
    ("linkedin-job", "linkedin.com", "professional"),
    ("linkedin-profile", "linkedin.com", "professional"),
    ("lowes-product", "lowes.com", "ecommerce"),
    ("lululemon-product", "lululemon.com", "ecommerce"),
    ("macys-product", "macys.com", "ecommerce"),
    ("medium-article", "medium.com", "content"),
    ("monster-job", "monster.com", "professional"),
    ("nbcnews-article", "nbcnews.com", "news"),
    ("newegg-product", "newegg.com", "ecommerce"),
    ("nike-product", "nike.com", "ecommerce"),
    ("nordstrom-product", "nordstrom.com", "ecommerce"),
    ("nytimes-article", "nytimes.com", "news"),
    ("officedepot-product", "officedepot.com", "ecommerce"),
    ("old-navy-product", "oldnavy.gap.com", "ecommerce"),
    ("petsmart-product", "petsmart.com", "ecommerce"),
    ("politico-article", "politico.com", "news"),
    ("pottery-barn-product", "potterybarn.com", "ecommerce"),
    ("producthunt-product", "producthunt.com", "business"),
    ("realtor-listing", "realtor.com", "real_estate"),
    ("reddit-post", "reddit.com", "social"),
    ("rei-product", "rei.com", "ecommerce"),
    ("reuters-article", "reuters.com", "news"),
    ("samsclub-product", "samsclub.com", "ecommerce"),
    ("scmp-article", "scmp.com", "news"),
    ("sec-edgar-filing", "sec.gov", "financial"),
    ("sephora-product", "sephora.com", "ecommerce"),
    ("staples-product", "staples.com", "ecommerce"),
    ("substack-article", "substack.com", "content"),
    ("target-product", "target.com", "ecommerce"),
    ("techcrunch-article", "techcrunch.com", "news"),
    ("theguardian-article", "theguardian.com", "news"),
    ("theverge-article", "theverge.com", "news"),
    ("tiktok-profile", "tiktok.com", "social"),
    ("time-article", "time.com", "news"),
    ("tripadvisor-attraction", "tripadvisor.com", "travel"),
    ("trustpilot-reviews", "trustpilot.com", "reviews"),
    ("twitter-profile", "twitter.com", "social"),
    ("ulta-product", "ulta.com", "ecommerce"),
    ("usatoday-article", "usatoday.com", "news"),
    ("uspto-patent", "uspto.gov", "reference"),
    ("walgreens-product", "walgreens.com", "ecommerce"),
    ("walmart-grocery-product", "walmart.com", "ecommerce"),
    ("walmart-product", "walmart.com", "ecommerce"),
    ("washingtonpost-article", "washingtonpost.com", "news"),
    ("wayfair-product", "wayfair.com", "ecommerce"),
    ("west-elm-product", "westelm.com", "ecommerce"),
    ("wikipedia-article", "wikipedia.org", "reference"),
    ("wired-article", "wired.com", "news"),
    ("wsj-article", "wsj.com", "news"),
    ("yahoo-finance-quote", "finance.yahoo.com", "financial"),
    ("yelp-business", "yelp.com", "reviews"),
    ("youtube-video", "youtube.com", "media"),
    ("zara-product", "zara.com", "ecommerce"),
    ("zerohedge-article", "zerohedge.com", "news"),
    ("zillow-listing", "zillow.com", "real_estate"),
    ("ziprecruiter-job", "ziprecruiter.com", "professional"),
]


async def test_all():
    failures = []
    async with httpx.AsyncClient(timeout=30) as c:
        for tid, site, _cat in TEMPLATES:
            print(f"Testing {tid}...", end=" ", flush=True)
            try:
                r = await c.post(
                    "http://localhost:8002/v1/templates/execute",
                    json={"template_id": tid, "url": f"https://www.{site}"},
                    timeout=30,
                )
                if r.is_success and r.json().get("success"):
                    print("OK")
                else:
                    print(f"FAIL: {r.text[:80]}")
                    failures.append(tid)
                await asyncio.sleep(0.5)
            except (httpx.HTTPError, httpx.RequestError) as e:
                print(f"ERR: {e}")
                failures.append(tid)

    print(f"\n{len(list(TEMPLATES))} tested, {len(failures)} failed")
    if failures:
        print("Failed:", ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test_all()))
