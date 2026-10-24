"""Robots gate and blocked-source bookkeeping (no network here)."""

from __future__ import annotations

from kol_discovery import sources

# Verbatim from https://x.com/robots.txt (2026-10-25), wildcard group only.
X_ROBOTS = """
User-agent: Googlebot
Allow: /i/api/*

User-agent: *
Disallow: /
Disallow: /i/u
Crawl-delay: 1
"""

ALLOW_ALL_ROBOTS = "User-agent: *\nDisallow:\n"


def test_x_com_profile_path_is_disallowed_for_us() -> None:
    assert sources.robots_allows(X_ROBOTS, "/cobie") is False


def test_named_group_wins_over_wildcard() -> None:
    robots = "User-agent: MyBot\nAllow: /\n\nUser-agent: *\nDisallow: /\n"
    assert sources.robots_allows(robots, "/cobie", user_agent="MyBot/1.0") is True
    assert sources.robots_allows(robots, "/cobie", user_agent="Other/1.0") is False


def test_empty_disallow_allows_everything() -> None:
    assert sources.robots_allows(ALLOW_ALL_ROBOTS, "/leaderboard") is True


def test_missing_robots_file_allows() -> None:
    assert sources.robots_allows("", "/leaderboard") is True


def test_longest_match_wins_and_allow_breaks_ties() -> None:
    robots = "User-agent: *\nDisallow: /priv\nAllow: /priv/open\n"
    assert sources.robots_allows(robots, "/priv/open/x") is True
    assert sources.robots_allows(robots, "/priv/x") is False


def test_wildcard_and_anchor_rules() -> None:
    robots = "User-agent: *\nDisallow: /*/followers$\n"
    assert sources.robots_allows(robots, "/cobie/followers") is False
    assert sources.robots_allows(robots, "/cobie/followers/more") is True


def test_live_probes_record_status_and_never_invent_data() -> None:
    rows, tally = sources.source_rows()
    assert tally["total"] == len(rows) == len(sources.LIVE_PROBES)
    assert tally["blocked"] + tally["reachable"] + tally["interfaces"] == tally["total"]
    assert tally["interfaces"] == 1, "the x-social-ops hop is an import, not a fetch"
    for row in rows:
        assert row["url"], row["name"]
        if row["status"] == sources.BLOCKED:
            assert row["detail"], f"{row['name']} blocked without a reason"
        else:
            assert row["yields"], f"{row['name']} reachable without stated fields"


def test_x_profile_is_blocked_and_kolscan_is_reachable() -> None:
    by_name = {probe.name: probe for probe in sources.LIVE_PROBES}
    assert by_name["x_profile_bio"].usable is False
    assert "robots" in by_name["x_profile_bio"].detail
    assert by_name["kolscan_leaderboard"].usable is True
