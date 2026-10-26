"""robots.txt gate: allowed paths pass, disallowed paths are typed refusals."""

from __future__ import annotations

import pytest

from pry.datasources.dextools_robots import robots_verdict

PAIR = "https://www.dextools.io/app/ether/pair-explorer/0xa43fe16908251ee70ef74718545e4fe6c5ccec9f"


def test_allowed_pair_path() -> None:
    assert robots_verdict(PAIR) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://www.dextools.io/api/core/search/pool?query=x",
        "https://www.dextools.io/api/core/pool/snipers/0xabc",
        "https://www.dextools.io/api/auth/login",
        "https://www.dextools.io/app/user",
        "https://www.dextools.io/stage",
    ],
)
def test_disallowed_paths_refused(url: str) -> None:
    verdict = robots_verdict(url)
    assert verdict is not None
    assert verdict.code == "blocked.robots"
    assert verdict.to_dict()["error"] == "refused"


def test_longest_match_wins() -> None:
    text = "User-agent: *\nDisallow: /api/core/\nDisallow: /api/core/search/pool\n"
    verdict = robots_verdict("/api/core/search/pool?q=1", text)
    assert verdict is not None
    assert "/api/core/search/pool" in verdict.reason
