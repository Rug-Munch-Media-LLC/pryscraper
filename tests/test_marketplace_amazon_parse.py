# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Unit tests for pry.commerce.marketplace.amazon pure parse helpers.

Every helper is exercised against locally-built lxml documents — no HTTP,
no fixtures fetched from the network. Covers ASIN validation, price/rating/
review extraction, Best Sellers Rank, offer counts, badges and category.
"""

from __future__ import annotations

from pry.commerce.marketplace import _lxml_doc
from pry.commerce.marketplace.amazon import (
    _amazon_badges,
    _amazon_bsr_category,
    _amazon_category,
    _amazon_offer_count,
    _amazon_price,
    _amazon_rating,
    _amazon_review_count,
    _valid_asin,
)


class TestValidAsin:
    def test_accepts_ten_char_alnum(self) -> None:
        assert _valid_asin("B08N5WRWNW") is True

    def test_lowercase_is_normalized(self) -> None:
        assert _valid_asin("b08n5wrwnw") is True

    def test_rejects_wrong_length(self) -> None:
        assert _valid_asin("TOOSHORT") is False

    def test_rejects_empty(self) -> None:
        assert _valid_asin("") is False


class TestAmazonPrice:
    def test_reads_offscreen_amount_and_currency(self) -> None:
        doc = _lxml_doc('<span class="a-price"><span class="a-offscreen">$19.99</span></span>')
        expected = (19.99, "USD")
        assert _amazon_price(doc) == expected

    def test_ignores_strikethrough_price_block(self) -> None:
        doc = _lxml_doc("<html></html>")
        expected = (0.0, "")
        assert _amazon_price(doc) == expected


class TestAmazonRating:
    def test_parses_numeric_rating(self) -> None:
        doc = _lxml_doc(
            '<span id="acrPopover"><span class="a-icon-alt">4.5 out of 5 stars</span></span>'
        )
        assert _amazon_rating(doc) == 4.5

    def test_missing_rating_is_zero(self) -> None:
        assert _amazon_rating(_lxml_doc("<p>none</p>")) == 0.0


class TestAmazonReviewCount:
    def test_parses_commas_in_count(self) -> None:
        doc = _lxml_doc('<span id="acrCustomerReviewText">1,234 ratings</span>')
        assert _amazon_review_count(doc) == 1234

    def test_missing_count_is_zero(self) -> None:
        assert _amazon_review_count(_lxml_doc("<p>none</p>")) == 0


class TestAmazonBsr:
    def test_extracts_rank_and_category_from_page_text(self) -> None:
        rank, category = _amazon_bsr_category(
            _lxml_doc("<p>body</p>"), "Best Sellers Rank: #1,234 in Electronics"
        )
        assert rank == 1234
        assert category == "Electronics"

    def test_absent_rank_returns_zero_and_empty(self) -> None:
        expected = (0, "")
        assert _amazon_bsr_category(_lxml_doc("<p>x</p>"), "no rank") == expected


class TestAmazonOfferCount:
    def test_counts_new_offers(self) -> None:
        assert _amazon_offer_count("New (12) from $5.00") == 12

    def test_no_offers_is_zero(self) -> None:
        assert _amazon_offer_count("nothing here") == 0


class TestAmazonBadges:
    def test_collects_badge_text(self) -> None:
        doc = _lxml_doc('<span class="a-badge-text">Amazon&#39;s Choice</span>')
        expected = ["Amazon's Choice"]
        assert _amazon_badges(doc) == expected

    def test_no_badge_returns_empty_list(self) -> None:
        assert _amazon_badges(_lxml_doc("<p>plain</p>")) == []


class TestAmazonCategory:
    def test_bsr_category_takes_precedence(self) -> None:
        assert _amazon_category(_lxml_doc("<p>x</p>"), "Books") == "Books"

    def test_empty_bsr_returns_empty(self) -> None:
        assert _amazon_category(_lxml_doc("<p>x</p>"), "") == ""
