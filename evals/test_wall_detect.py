"""Regression: wall detection must be a head signal, not a substring of the body."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import scrape_matrix
import wall_detect

FIX = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "scrape"
GITHUB = (FIX / "github_page.html").read_text()
CHALLENGE = (FIX / "challenge_page.html").read_text()


def test_fixture_reproduces_the_false_positive() -> None:
    """The recorded GitHub page really does carry a challenge word in its body."""
    assert "captcha" in GITHUB[:200_000].lower()
    assert wall_detect.is_wall(GITHUB) is False


def test_normal_page_is_ok() -> None:
    verdict = scrape_matrix.classify(
        200, len(GITHUB.encode()), scrape_matrix.count_fields(GITHUB), GITHUB
    )
    assert verdict == "ok"


def test_challenge_page_is_wall() -> None:
    assert wall_detect.is_wall(CHALLENGE) is True
    verdict = scrape_matrix.classify(
        200, len(CHALLENGE.encode()), scrape_matrix.count_fields(CHALLENGE), CHALLENGE
    )
    assert verdict == "wall"


def test_block_status_still_wall() -> None:
    assert scrape_matrix.classify(429, 20, 0, "") == "wall"
    assert scrape_matrix.classify(403, 5672, 1, GITHUB) == "wall"
