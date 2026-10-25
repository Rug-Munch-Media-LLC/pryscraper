"""Tests for the US geo-fenced sportsbook odds fetchers (sports_data.us_books).

Covers the 11-book registry, the reverse-engineered JSON parsers (DraftKings
eventgroup shape, FanDuel eventGroup + cache shapes, PointsBet featured
events, generic events), the Webshare-US-proxy transport with Tor fallback,
geo-block degrade and the never-raise contract.

All HTTP is mocked (aiohttp session mocks / monkeypatched transport) — no
live network, no real Webshare proxies, no Tor daemon.
"""
import datasets.sports_data.us_books as us


class TestRegistry:
    """US_BOOKS must carry the documented per-book contract fields."""

    REQUIRED_KEYS = (
        "id",
        "name",
        "category",
        "odds_url_template",
        "method",
        "geo_required",
        "confidence",
    )

    def test_eleven_books_registered(self) -> None:
        expected = {
            "draftkings",
            "fanduel",
            "betmgm",
            "caesars",
            "pointsbet",
            "betrivers",
            "barstool",
            "wynnbet",
            "betway_us",
            "hardrock",
            "espnbet",
        }
        assert set(us.US_BOOKS) == expected

    def test_every_book_has_contract_fields(self) -> None:
        for book_id, entry in us.US_BOOKS.items():
            for key in self.REQUIRED_KEYS:
                assert key in entry, f"{book_id} missing {key}"
            assert entry["id"] == book_id
            assert entry["category"] == "us"
            assert entry["method"] == "json"
            assert entry["geo_required"] is True
            assert 0.0 <= float(entry["confidence"]) <= 1.0
            assert "{category_id" not in entry["odds_url_template"] or book_id == "draftkings"

    def test_book_status_shape(self) -> None:
        status = us.book_status()
        assert set(status) == set(us.US_BOOKS)
        first = status["draftkings"]
        assert first["name"] == "DraftKings"
        assert first["category"] == "us"
        expected = {
            "reachable",
            "blocked",
            "last_checked",
            "latency_ms",
            "error",
        }
        assert set(first["availability"]) == expected
