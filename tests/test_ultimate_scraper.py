"""Tests for ultimate scraper."""

from ultimate_scraper import UltimateScraper


def test_ultimate_init() -> None:
    s = UltimateScraper()
    assert s is not None
    assert len(s.USER_AGENTS) >= 3


def test_rotate_ua_changes() -> None:
    s = UltimateScraper()
    ua1 = s._rotate_ua()
    ua2 = s._rotate_ua()
    assert isinstance(ua1, str)
    assert isinstance(ua2, str)


def test_is_valid_empty() -> None:
    s = UltimateScraper()
    assert s._is_valid("") is False
    assert s._is_valid("<html></html>") is False
    assert s._is_valid(None) is False
