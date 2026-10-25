# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Behaviour tests for the actor crawl loop (``apify_actor.runner.main``).

The actor is a distribution channel: what a dataset consumer receives for
success, scrape error, invalid URL and invalid input is pinned here, along
with the crawl frontier and the ``max_pages`` boundary.
"""

from __future__ import annotations

from tests.fixtures_apify import FakeActor, FakeScraper, ok, run


class TestInputAndUrlFailurePaths:
    async def test_invalid_input_pushes_error_item_and_never_scrapes(self) -> None:
        actor = FakeActor({"urls": []})
        scraper = FakeScraper([])
        await run(actor, scraper)

        assert scraper.calls == []
        assert len(actor.pushed) == 1
        assert actor.pushed[0]["status"] == "error"
        assert actor.pushed[0]["error"].startswith("Invalid input:")
        assert "pry_actor_input_invalid" in actor.log.events("error")

    async def test_invalid_url_pushes_error_item_and_continues(self) -> None:
        actor = FakeActor({"urls": ["file:///etc/passwd", "https://example.com/ok"]})
        scraper = FakeScraper([ok()])
        await run(actor, scraper)

        assert [call[0] for call in scraper.calls] == ["https://example.com/ok"]
        assert len(actor.pushed) == 2
        assert actor.pushed[0]["status"] == "error"
        assert actor.pushed[0]["url"] == "file:///etc/passwd"
        assert actor.pushed[0]["error"].startswith("Invalid URL:")
        assert actor.pushed[1]["status"] == "ok"
        assert "pry_actor_skip_invalid" in actor.log.events("warning")

    async def test_scrape_error_is_pushed_and_counted(self) -> None:
        actor = FakeActor({"urls": ["https://example.com/a"]})
        scraper = FakeScraper([{"status": "error", "error": "blocked", "method": "flaresolverr"}])
        await run(actor, scraper)

        assert actor.pushed[0]["status"] == "error"
        assert actor.pushed[0]["error"] == "blocked"
        # exclude_none only: empty strings stay, so consumers always see the field
        assert actor.pushed[0]["content"] == ""
        assert actor.state["STATE"]["total_errors"] == 1


class TestCrawlLoop:
    async def test_success_pushes_one_item_per_url(self) -> None:
        actor = FakeActor(
            {"urls": ["https://example.com/a", "https://example.com/b"], "max_pages": 2}
        )
        scraper = FakeScraper([ok("one"), ok("two")])
        await run(actor, scraper)

        assert [item["url"] for item in actor.pushed] == [
            "https://example.com/a",
            "https://example.com/b",
        ]
        assert all(item["status"] == "ok" for item in actor.pushed)
        assert actor.state["STATE"] == {
            "visited": 2,
            "total_scraped": 2,
            "total_errors": 0,
            "queue_remaining": 0,
        }
        assert "pry_actor_finish" in actor.log.events("info")

    async def test_default_max_pages_caps_a_multi_url_run_at_one(self) -> None:
        """max_pages defaults to 1 — a two-URL input still scrapes one page."""
        actor = FakeActor({"urls": ["https://example.com/a", "https://example.com/b"]})
        scraper = FakeScraper([ok("one"), ok("two")])
        await run(actor, scraper)

        assert len(scraper.calls) == 1
        assert len(actor.pushed) == 1
        assert actor.state["STATE"]["queue_remaining"] == 1

    async def test_max_pages_boundary_stops_after_one_page(self) -> None:
        actor = FakeActor(
            {
                "urls": ["https://example.com/a", "https://example.com/b"],
                "max_pages": 1,
                "crawl": True,
            }
        )
        scraper = FakeScraper([ok(html='<a href="/next">n</a>'), ok(html='<a href="/next">n</a>')])
        await run(actor, scraper)

        assert len(scraper.calls) == 1
        assert len(actor.pushed) == 1

    async def test_crawl_mode_enqueues_discovered_links(self) -> None:
        html = '<a href="/next">n</a><a href="https://other.com/x">x</a>'
        actor = FakeActor({"urls": ["https://example.com/a"], "max_pages": 2, "crawl": True})
        scraper = FakeScraper([ok(html=html), ok("second")])
        await run(actor, scraper)

        assert [call[0] for call in scraper.calls] == [
            "https://example.com/a",
            "https://example.com/next",
        ]
        assert "pry_actor_links_discovered" in actor.log.events("debug")

    async def test_no_crawl_means_no_link_extraction(self) -> None:
        actor = FakeActor({"urls": ["https://example.com/a"], "max_pages": 5})
        scraper = FakeScraper([ok(html='<a href="/next">n</a>')])
        await run(actor, scraper)

        assert len(scraper.calls) == 1
