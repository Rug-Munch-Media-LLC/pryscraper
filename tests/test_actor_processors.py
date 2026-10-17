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
        # no og tags in this fixture -> flagged by the new social-card audit
        expected = {"missing_og_title", "missing_og_image"}
        assert set(seo["issues"]) == expected

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


class TestSeoExtendedSignals:
    """og-tags / alt-audit / privacy markers added for gap-filler actors."""

    PAGE = (
        "<html><head><title>T</title>"
        '<meta property="og:title" content="Social Title">'
        '<meta property="og:image" content="https://e.com/img.png">'
        "</head><body>"
        '<h1>H</h1><img src="a.png"><img src="b.png" alt="described">'
        '<a href="/privacy">Privacy</a>'
        "<script>cookieconsent</script>"
        "</body></html>"
    )

    def test_og_tags_extracted(self) -> None:
        item = process_seo("http://e.com/", _ok_result(self.PAGE), {}, {})
        assert item["seo"]["og_tags"]["og:title"] == "Social Title"
        assert item["seo"]["og_tags"]["og:image"] == "https://e.com/img.png"

    def test_alt_audit_counts_missing(self) -> None:
        item = process_seo("http://e.com/", _ok_result(self.PAGE), {}, {})
        assert item["seo"]["images_total"] == 2
        assert item["seo"]["images_missing_alt"] == 1

    def test_privacy_markers_detected(self) -> None:
        item = process_seo("http://e.com/", _ok_result(self.PAGE), {}, {})
        markers = item["seo"]["privacy_markers"]
        assert markers["cookie_banner"] is True
        assert markers["privacy_page_linked"] is True


class TestLeadsContactForms:
    def test_contact_form_and_mailto_detected(self) -> None:
        html = '<form action="/submit"></form><a href="mailto:x@e.com">mail</a>'
        item = process_leads("http://e.com", _ok_result(html), {}, {})
        assert item["leads"]["contact_form_present"] is True


class TestBacklinksProcessor:
    def test_external_domains_deduped_internal_excluded(self) -> None:
        from actor_factory.processors import process_backlinks

        html = (
            '<a href="https://other.com/a">x</a>'
            '<a href="https://other.com/b">dup-domain</a>'
            '<a href="/internal">i</a>'
            '<a href="https://third.io/">t</a>'
        )
        item = process_backlinks("http://mysite.com/x", {"status": "ok", "raw_html": html}, {}, {})
        expected = ["other.com", "third.io"]
        assert item["outbound_domains"] == expected


class TestAuditProcessor:
    def test_accessibility_findings_ranked(self) -> None:
        from actor_factory.processors import process_audit

        html = '<html><body><img src="a.png"><img src="b.png" alt="b"><p>hello</p></body></html>'
        item = process_audit("http://e.com", _ok_result(html), {}, {})
        audit = item["audit"]
        assert audit["failed"] + audit["warnings"] >= 1
        checks = {f["check"]: f for f in audit["findings"]}
        assert checks["images_alt_text"]["status"] == "warn"  # 1 of 2 missing
        assert 0 <= audit["score"] <= 100
        assert "content" not in item  # raw HTML never shipped to dataset

    def test_gdpr_fail_without_privacy_link(self) -> None:
        from actor_factory.processors import process_audit

        html = "<html><head><script src='https://x.cookiebot.com/s.js'></script></head><body>hi</body></html>"
        item = process_audit("http://e.com", _ok_result(html), {"check_accessibility": False}, {})
        checks = {f["check"]: f for f in item["audit"]["findings"]}
        assert checks["cookie_consent_mechanism"]["status"] == "ok"
        assert checks["privacy_policy_link"]["status"] == "fail"

    def test_error_item_passes_through(self) -> None:
        from actor_factory.processors import process_audit

        item = process_audit("http://e.com", {"status": "error", "error": "boom"}, {}, {})
        assert item["status"] == "error"
        assert "audit" not in item


class TestMonitorProcessor:
    def test_baseline_then_change_detection(self) -> None:
        from actor_factory.processors import process_monitor

        state: dict = {}
        first = process_monitor("http://e.com", _ok_result("v1 content"), {}, state)
        assert first["monitor"]["changed"] is None  # baseline run
        assert first["monitor"]["detail"] == "baseline captured"

        same = process_monitor("http://e.com", _ok_result("v1 content"), {}, state)
        assert same["status"] == "skipped"  # unchanged suppressed by default
        assert same["monitor"]["changed"] is False

        opts = {"include_unchanged": True}
        kept = process_monitor("http://e.com", _ok_result("v1 content"), opts, state)
        assert kept["status"] == "ok"

        diff = process_monitor(
            "http://e.com",
            _ok_result("v2 page", content="y" * 600),
            {},
            state,
        )
        assert diff["monitor"]["changed"] is True


class TestExtractProcessor:
    def test_jsonld_recipe_extracted(self) -> None:
        import json as _json

        from actor_factory.processors import process_extract

        recipe = _json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Pancakes",
                "recipeYield": "4",
                "prepTime": "PT10M",
            }
        )
        html = f'<html><head><script type="application/ld+json">{recipe}</script></head><body>x</body></html>'
        item = process_extract("http://e.com", _ok_result(html), {"types": ["Recipe"]}, {})
        entities = item["extracted"]["entities"]
        assert entities[0]["type"] == "Recipe"
        assert entities[0]["fields"]["name"] == "Pancakes"
        assert entities[0]["fields"]["prepTime"] == "PT10M"

    def test_no_structured_data_skips_honestly(self) -> None:
        from actor_factory.processors import process_extract

        item = process_extract("http://e.com", _ok_result("<p>plain</p>"), {}, {})
        assert item["status"] == "skipped"
        assert "structured data" in item["error"]

    def test_type_filter_excludes_other_entities(self) -> None:
        import json as _json

        from actor_factory.processors import process_extract

        data = _json.dumps({"@type": "Product", "name": "Widget"})
        html = f'<script type="application/ld+json">{data}</script>'
        item = process_extract("http://e.com", _ok_result(html), {"types": ["Recipe"]}, {})
        assert item["status"] == "skipped"


class TestProcessorRegistryNew:
    def test_new_processors_registered(self) -> None:
        from actor_factory.processors import get_processor

        for name in ("audit", "monitor", "extract"):
            assert callable(get_processor(name))


class TestTechProcessor:
    def test_signatures_detected_and_content_suppressed(self) -> None:
        from actor_factory.processors import process_tech

        html = (
            "<html><head>"
            '<meta name="generator" content="WordPress 6.4">'
            '<script src="https://cdn.shopify.com/s.js"></script>'
            '<script src="https://js.stripe.com/v3"></script>'
            "</head><body>shop</body></html>"
        )
        item = process_tech("http://e.com", _ok_result(html), {}, {})
        tech = item["tech"]
        names = {t["name"] for t in tech["technologies"]}
        # generator meta keeps its full versioned string; signature hits
        # match canonical names
        assert "WordPress 6.4" in names
        assert any(t["category"] == "generator_meta" for t in tech["technologies"])
        assert "Shopify" in names
        assert "Stripe" in names
        assert tech["count"] == len(tech["technologies"]) >= 3
        assert "ecommerce" in tech["categories"]
        assert "content" not in item

    def test_clean_page_reports_empty_honestly(self) -> None:
        from actor_factory.processors import process_tech

        item = process_tech("http://e.com", _ok_result("<p>plain</p>"), {}, {})
        assert item["tech"]["count"] == 0
        assert item["tech"]["technologies"] == []

    def test_error_item_passthrough(self) -> None:
        from actor_factory.processors import process_tech

        item = process_tech("http://e.com", {"status": "error", "error": "x"}, {}, {})
        assert item["status"] == "error"
        assert "tech" not in item


class TestNewCatalogEntries:
    def test_four_new_presets_wired_and_priced(self) -> None:
        from actor_factory.presets import ALL_PRESETS

        expected = {
            "pry-product-data-extractor": "extract",
            "pry-ecommerce-catalog-crawler": "extract",
            "pry-knowledge-base-miner": "extract",
            "pry-local-business-schema-auditor": "extract",
            "pry-tech-stack-detector": "tech",
        }
        for name, proc in expected.items():
            spec = ALL_PRESETS[name]
            assert spec.processor == proc, name
            assert len(spec.description) >= 80, name
            assert spec.pricing_events, name

    def test_catalog_has_no_duplicate_titles(self) -> None:
        from collections import Counter

        from actor_factory.presets import ALL_PRESETS

        dupes = [t for t, c in Counter(s.title for s in ALL_PRESETS.values()).items() if c > 1]
        assert not dupes, dupes


class TestJsonLdUnquotedAttributes:
    def test_yoast_style_unquoted_type_attribute(self) -> None:
        """Regression: Yoast emits <script type=application/ld+json ...>
        unquoted (valid HTML5). Found via live back-testing against
        loveandlemons.com - millions of WP sites affected."""
        import json as _json

        from actor_factory.processors import process_extract

        data = _json.dumps(
            {
                "@context": "https://schema.org",
                "@graph": [{"@type": "Recipe", "name": "Hummus"}],
            }
        )
        html = f"<script type=application/ld+json class=yoast-schema-graph>{data}</script>"
        item = process_extract("http://e.com", _ok_result(html), {"types": ["Recipe"]}, {})
        assert item["status"] == "ok"
        assert item["extracted"]["entities"][0]["fields"]["name"] == "Hummus"


class TestJsonDataProcessor:
    def test_parses_json_payload_with_data_path(self) -> None:
        from actor_factory.processors import process_jsondata

        body = '{"ok":true,"items":[{"name":"a","v":1},{"name":"b","v":2}]}'
        item = process_jsondata("http://api", _ok_result(body), {"data_path": "items"}, {})
        assert item["status"] == "ok"
        recs = item["data"]["records"]
        assert len(recs) == 2
        assert recs[0]["name"] == "a"
        assert item["data"]["count"] == 2

    def test_non_json_skips_honestly(self) -> None:
        from actor_factory.processors import process_jsondata

        item = process_jsondata("http://x", _ok_result("<html>hi</html>"), {}, {})
        assert item["status"] == "skipped"
        assert "not JSON" in item["error"]

    def test_invalid_json_reports_reason(self) -> None:
        from actor_factory.processors import process_jsondata

        item = process_jsondata("http://x", _ok_result("{broken"), {}, {})
        assert item["status"] == "skipped"
        assert "invalid JSON" in item["error"]

    def test_missing_data_path_yields_empty_records(self) -> None:
        from actor_factory.processors import process_jsondata

        item = process_jsondata(
            "http://api", _ok_result('{"other": []}'), {"data_path": "nope.here"}, {}
        )
        assert item["data"]["records"] == []

    def test_max_items_caps_output(self) -> None:
        from actor_factory.processors import process_jsondata

        body = "[" + ",".join(f'{{"i":{n}}}' for n in range(100)) + "]"
        item = process_jsondata("http://api", _ok_result(body), {"max_items": 5}, {})
        assert item["data"]["count"] == 5
        assert item["data"]["total_in_response"] == 100


class TestInvoiceProcessor:
    def test_extracts_number_date_total(self) -> None:
        from actor_factory.processors import process_invoice

        text = (
            "ACME Corp\nInvoice No: INV-2026-0042\nInvoice Date: 2026-08-24\n"
            "Subtotal: 90.00\nGrand Total: $109.00\nThanks!"
        )
        item = process_invoice("file:///inv.pdf", _ok_result("pdf", content=text), {}, {})
        inv = item["invoice"]
        assert inv["number"] == "INV-2026-0042"
        assert inv["date"] == "2026-08-24"
        assert inv["total"] == "109.00"
        assert inv["currency"] == "$"

    def test_no_invoice_fields_skips_honestly(self) -> None:
        from actor_factory.processors import process_invoice

        item = process_invoice("file:///x.pdf", _ok_result("pdf", content="random text"), {}, {})
        assert item["status"] == "skipped"


class TestNewCatalogBatch20:
    def test_fifteen_api_backed_presets_wired(self) -> None:
        from actor_factory.presets import ALL_PRESETS

        expected = {
            "pry-app-store-review-miner": "jsondata",
            "pry-github-release-monitor": "jsondata",
            "pry-npm-package-stats": "jsondata",
            "pry-pypi-package-stats": "jsondata",
            "pry-hacker-news-monitor": "jsondata",
            "pry-youtube-rss-monitor": "monitor",
            "pry-rss-feed-monitor": "monitor",
            "pry-rdap-domain-watch": "jsondata",
            "pry-arxiv-paper-monitor": "jsondata",
            "pry-json-api-monitor": "jsondata",
            "pry-pdf-invoice-extractor": "invoice",
            "pry-startup-funding-monitor": "news",
            "pry-podcast-review-miner": "jsondata",
            "pry-fx-rate-monitor": "jsondata",
            "pry-crypto-market-monitor": "jsondata",
        }
        for name, proc in expected.items():
            spec = ALL_PRESETS[name]
            assert spec.processor == proc, name
            assert len(spec.description) >= 80, name


class TestCatalogBatch21:
    def test_fifteen_prediction_defi_gov_actors_wired(self) -> None:
        from actor_factory.presets import ALL_PRESETS

        expected = {
            "pry-prediction-market-monitor": "jsondata",
            "pry-sports-odds-best-line": "jsondata",
            "pry-token-unlock-monitor": "jsondata",
            "pry-defi-yield-monitor": "jsondata",
            "pry-chain-tvl-monitor": "jsondata",
            "pry-stablecoin-flow-monitor": "jsondata",
            "pry-whale-transfer-monitor": "jsondata",
            "pry-gas-fee-monitor": "jsondata",
            "pry-usaspending-contracts": "jsondata",
            "pry-fda-recall-monitor": "jsondata",
            "pry-uspto-patent-monitor": "jsondata",
            "pry-earthquake-alert-monitor": "jsondata",
            "pry-space-launch-monitor": "jsondata",
            "pry-steam-game-stats": "jsondata",
            "pry-producthunt-launch-monitor": "monitor",
        }
        for name, proc in expected.items():
            spec = ALL_PRESETS[name]
            assert spec.processor == proc, name
            assert len(spec.description) >= 80, name
            assert spec.pricing_events, name
