# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for per-preset dataset-item processors (factory layer 5).

Each niche actor must DO what its store description promises. These tests
prove the processors against fixture HTML - no network, no SDK.
"""

from __future__ import annotations

from actor_factory.processors import (
    process_corpus,
    process_leads,
    process_news,
    process_price,
    process_seo,
)


def _ok_result(html: str, content: str = "x" * 600) -> dict:
    return {
        "status": "ok",
        "raw_html": html,
        "content": content,
        "method": "direct",
        "scraped_at": "2026-08-23T00:00:00+00:00",
    }


class TestCorpusProcessor:
    def test_short_content_skipped(self) -> None:
        result = _ok_result("<p>hi</p>", content="tiny")
        item = process_corpus("http://e.com/1", result, {"min_content_chars": 500}, {})
        assert item["status"] == "skipped"
        assert "500" in item["error"]

    def test_near_duplicate_skipped(self) -> None:
        state: dict = {}
        text = "the quick brown fox " * 40
        first = process_corpus("http://e.com/a", _ok_result("<p>x</p>", content=text), {}, state)
        assert first["status"] == "ok"
        second = process_corpus("http://e.com/b", _ok_result("<p>y</p>", content=text), {}, state)
        assert second["status"] == "skipped"
        assert "near-duplicate" in second["error"]

    def test_dedupe_disabled_passes_duplicates(self) -> None:
        state: dict = {}
        opts = {"dedupe": False}
        text = "same words " * 50
        a = process_corpus("http://e.com/a", _ok_result("<p></p>", content=text), opts, state)
        b = process_corpus("http://e.com/b", _ok_result("<p></p>", content=text), opts, state)
        assert a["status"] == "ok"
        assert b["status"] == "ok"


PAGE_HTML = """
<html><head>
<title>Best Running Shoes 2026</title>
<meta name="description" content="Reviews of the best running shoes.">
<link rel="canonical" href="https://shop.example/shoes">
</head><body>
<h1>Running Shoes</h1><h2>Pick One</h2><h2>Wrap Up</h2>
<p>content body text here</p>
</body></html>
"""


class TestSeoProcessor:
    def test_signals_extracted(self) -> None:
        item = process_seo("http://e.com/shoes", _ok_result(PAGE_HTML), {}, {})
        seo = item["seo"]
        assert seo["title"] == "Best Running Shoes 2026"
        assert seo["meta_description"] == "Reviews of the best running shoes."
        assert seo["canonical"] == "https://shop.example/shoes"
        assert len(seo["headings"]["h2"]) == 2
        assert seo["issues"] == []

    def test_missing_signals_flagged_as_issues(self) -> None:
        item = process_seo("http://e.com/bare", _ok_result("<p>no head</p>"), {}, {})
        assert set(item["seo"]["issues"]) >= {"missing_title", "missing_meta_description"}

    def test_long_title_flagged(self) -> None:
        long_title = "T" * 80
        item = process_seo("http://e.com/x", _ok_result(f"<title>{long_title}</title>"), {}, {})
        assert "title_too_long" in item["seo"]["issues"]

    def test_error_result_passthrough(self) -> None:
        item = process_seo("http://e.com/dead", {"status": "error", "error": "down"}, {}, {})
        assert item["status"] == "error"
        assert "seo" not in item


LEAD_HTML = """
<html><body>
Contact us at sales@acme.example or call +1 (555) 123-4567.
Find us on https://www.linkedin.com/company/acme and https://x.com/acme_inc
Duplicate: sales@acme.example
</body></html>
"""


class TestLeadsProcessor:
    def test_emails_phones_socials_extracted_and_deduped(self) -> None:
        item = process_leads("http://acme.example", _ok_result(LEAD_HTML), {}, {})
        leads = item["leads"]
        assert leads["emails"].count("sales@acme.example") == 1
        assert any("555" in p for p in leads["phones"])
        assert any("linkedin" in s for s in leads["social_links"])
        assert any("x.com" in s for s in leads["social_links"])

    def test_social_links_excluded_when_disabled(self) -> None:
        item = process_leads(
            "http://acme.example", _ok_result(LEAD_HTML), {"include_social_links": False}, {}
        )
        assert item["leads"]["social_links"] == []


NEWS_HTML = """
<html><body>
<a href="/2026/08/big-story">Big Story</a>
<a href="/2026/08/other#frag">Other</a>
<a href="https://ext.com/2026/piece">External</a>
<a href="/about">About</a>
</body></html>
"""


class TestNewsProcessor:
    def test_article_links_resolved_capped_deduped(self) -> None:
        item = process_news(
            "http://news.example/", _ok_result(NEWS_HTML), {"max_articles_per_source": 10}, {}
        )
        articles = item["articles"]
        assert "http://news.example/2026/08/big-story" in articles
        assert "https://ext.com/2026/piece" in articles
        assert not any("#frag" in a for a in articles)
        assert "/about" not in "".join(articles)

    def test_cap_respected(self) -> None:
        item = process_news(
            "http://news.example/", _ok_result(NEWS_HTML), {"max_articles_per_source": 1}, {}
        )
        assert len(item["articles"]) == 1


PRICE_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "Product", "name": "Trail Runner Pro",
 "offers": {"price": "129.99", "priceCurrency": "USD"}}
</script>
</head><body><p>Buy it.</p></body></html>
"""

PRICE_HTML_NO_DATA = "<html><body><span>$49.99</span></body></html>"


class TestPriceProcessor:
    def test_jsonld_product_price_extracted(self) -> None:
        item = process_price("http://e.com/p/1", _ok_result(PRICE_HTML), {}, {})
        assert item["status"] == "ok"
        assert item["product"]["price"] == 129.99
        assert item["product"]["currency"] == "USD"
        assert item["product"]["name"] == "Trail Runner Pro"

    def test_missing_structured_data_is_explicit_error(self) -> None:
        """Docs pattern: charge for invalid targets, return error items."""
        item = process_price("http://e.com/p/2", _ok_result(PRICE_HTML_NO_DATA), {}, {})
        assert item["status"] == "error"
        assert "no structured product price" in item["error"]

    def test_currency_hint_used_when_absent(self) -> None:
        item = process_price(
            "http://e.com/p/3", _ok_result(PRICE_HTML), {"currency_hint": "EUR"}, {}
        )
        # JSON-LD carries USD explicitly, so hint must NOT override it.
        assert item["product"]["currency"] == "USD"


class TestProcessorRegistry:
    def test_registry_keys_match_preset_declarations(self) -> None:
        from actor_factory.presets import ALL_PRESETS
        from actor_factory.processors import PROCESSORS

        for spec in ALL_PRESETS.values():
            if spec.processor is not None:
                assert spec.processor in PROCESSORS, f"{spec.name}: {spec.processor}"
