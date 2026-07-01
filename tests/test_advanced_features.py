"""Tests for advanced features (cookie warming, PDF, OCR, dedup, behavior)."""

from behavioral_biometrics import HumanBehaviorSimulator
from cookie_warmer import WARMING_PAGES, CookieWarmer
from dedup import Deduplicator, SimHash
from ocr_extractor import ImageOCR
from pdf_extractor import PDFTableExtractor


def test_warming_pages_exist() -> None:
    assert "amazon" in WARMING_PAGES
    assert "twitter" in WARMING_PAGES
    assert len(WARMING_PAGES["amazon"]) >= 3


def test_warmer_init() -> None:
    w = CookieWarmer()
    assert w is not None


def test_pdf_extractor_init() -> None:
    p = PDFTableExtractor()
    assert p.prefer_method in ("pdfplumber", "camelot", "pdfminer")


def test_ocr_languages() -> None:
    o = ImageOCR()
    assert "eng" in o.SUPPORTED_LANGUAGES
    assert "spa" in o.SUPPORTED_LANGUAGES


def test_simhash_basic() -> None:
    h1 = SimHash.hash("the quick brown fox")
    h2 = SimHash.hash("the quick brown fox")
    assert h1 == h2
    h3 = SimHash.hash("completely different text here")
    assert SimHash.similarity(h1, h3) < 0.7


def test_simhash_similarity() -> None:
    h1 = SimHash.hash("hello world test")
    h2 = SimHash.hash("hello world test")
    assert SimHash.similarity(h1, h2) == 1.0
    h3 = SimHash.hash("totally different content")
    assert SimHash.similarity(h1, h3) < 0.8


def test_deduplicator() -> None:
    d = Deduplicator(threshold=0.8)
    d.add("doc1", "the quick brown fox jumps over the lazy dog")
    d.add("doc2", "the quick brown fox jumps over the lazy dog")
    d.add("doc3", "completely different content with no similarity at all")
    dupes = d.find_duplicates("the quick brown fox jumps over the lazy dog")
    assert any(entry["doc_id"] == "doc1" for entry in dupes)


def test_dedup_diff() -> None:
    d = Deduplicator()
    result = d.diff("hello world", "hello world")
    assert result["changed"] is False
    result2 = d.diff("hello world", "totally different content")
    assert result2["changed"] is True


def test_behavior_mouse_path() -> None:
    b = HumanBehaviorSimulator()
    path = b.mouse_path((0, 0), (100, 100))
    assert len(path) > 5
    # First point has ±2 jitter from bezier
    assert abs(path[0]["x"]) <= 2
    # Last point has ±2 jitter from bezier
    assert abs(path[-1]["x"] - 100) <= 2


def test_behavior_reading_pause() -> None:
    b = HumanBehaviorSimulator()
    pause = b.reading_pause(1000)
    assert 0 < pause < 120


def test_behavior_scroll_pattern() -> None:
    b = HumanBehaviorSimulator()
    pattern = b.scroll_pattern(2000, viewport_height=800)
    assert len(pattern) >= 1
    assert pattern[-1]["y"] >= 1900  # Should scroll to near bottom


def test_behavior_typing() -> None:
    b = HumanBehaviorSimulator()
    timings = b.typing_pattern("the quick brown fox")
    assert len(timings) == 4  # 4 words
    # Common words should be faster than uncommon
    common_delay = sum(t["delay_ms"] for t in timings[:1])  # "the" is common
    assert common_delay < 500


def test_behavior_click_delay() -> None:
    b = HumanBehaviorSimulator()
    for _ in range(10):
        delay = b.click_decision_delay()
        assert 0.2 <= delay <= 2.5


def test_behavior_form_sequence() -> None:
    b = HumanBehaviorSimulator()
    seq = b.form_filling_sequence(3)
    actions = [s["action"] for s in seq]
    assert "type" in actions
    assert "tab" in actions
    assert "submit" in actions
