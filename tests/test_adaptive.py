"""Tests for adaptive crawling."""

import asyncio

from adaptive import AdaptiveCrawler


def test_adaptive_init() -> None:
    c = AdaptiveCrawler(max_pages=10)
    assert c.max_pages == 10
    assert c._total_pages == 0


def test_should_continue_below_min_pages() -> None:
    c = AdaptiveCrawler(min_pages=3)
    result = asyncio.run(c.should_continue("https://example.com", "Some content here", 0))
    assert result["continue"] is True
    assert "below minimum" in result["reason"].lower()


def test_should_continue_relevance_high() -> None:
    c = AdaptiveCrawler(relevance_threshold=0.3)
    result = asyncio.run(
        c.should_continue("https://example.com", "Python programming guide", 0, query="python")
    )
    assert result["continue"] is True
    assert result["relevance_score"] > 0


def test_should_continue_max_pages() -> None:
    c = AdaptiveCrawler(max_pages=3, min_pages=0)
    results = []
    for i in range(3):
        r = asyncio.run(c.should_continue(f"https://example.com/{i}", f"Content {i}", 0))
        results.append(r)
    r = asyncio.run(c.should_continue("https://example.com/3", "Content 3", 0))
    assert r["continue"] is False
    assert "max pages" in r["reason"].lower()


def test_should_continue_max_depth() -> None:
    c = AdaptiveCrawler(max_depth=2, min_pages=0)
    r = asyncio.run(c.should_continue("https://example.com", "Content", 2))
    assert r["continue"] is False
    assert "max depth" in r["reason"].lower()


def test_get_stats() -> None:
    c = AdaptiveCrawler()
    asyncio.run(c.should_continue("https://example.com", "Hello world test", 0))
    stats = c.get_stats()
    assert stats["pages_crawled"] >= 1
    assert "avg_relevance" in stats


def test_reset() -> None:
    c = AdaptiveCrawler()
    asyncio.run(c.should_continue("https://example.com", "Test", 0))
    c.reset()
    assert c._total_pages == 0
    assert len(c._visited) == 0
