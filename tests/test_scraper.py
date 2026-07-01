import pytest

from scraper import PryScraper


@pytest.mark.asyncio
async def test_scraper_invalid_url() -> None:
    s = PryScraper()
    result = await s._scrape_attempt("not-a-url", {}, 0)
    assert result["status"] == "error"


def test_scraper_quality_score_high() -> None:
    s = PryScraper()
    content = "This is a test article. " * 50
    score = s._quality_score(content)
    assert score >= 20


def test_scraper_quality_score_empty() -> None:
    s = PryScraper()
    score = s._quality_score("")
    assert score == 0


def test_scraper_quality_score_low() -> None:
    s = PryScraper()
    score = s._quality_score("short")
    assert score < 20


def test_scraper_rotate_ua_changes() -> None:
    s = PryScraper()
    ua1 = s._rotate_ua()
    ua2 = s._rotate_ua()
    assert ua1 != ua2 or s._ua_index != 0


def test_scraper_build_headers_shape() -> None:
    s = PryScraper()
    headers = s._build_headers("https://example.com")
    assert "User-Agent" in headers
    assert "Accept" in headers
    assert "Accept-Language" in headers
    assert headers["User-Agent"].startswith("Mozilla")


def test_scraper_extract_title() -> None:
    s = PryScraper()
    html = "<html><head><title>Test Title</title></head><body><p>Hello</p></body></html>"
    result = s._extract(html, "https://example.com", {})
    assert result["title"] == "Test Title"


def test_scraper_extract_content_via_markdownify() -> None:
    s = PryScraper()
    html = "<html><body><p>Simple paragraph text here.</p></body></html>"
    result = s._extract(html, "https://example.com", {})
    assert "content" in result
    assert len(result["content"]) > 0
