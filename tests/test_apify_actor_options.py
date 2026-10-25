# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Scraper-option translation and the public dataset contract of the actor."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import pry.actors.apify_actor as actor_pkg
from pry.actors.apify_actor import ApifyActorInput, ApifyActorOutput, build_base_options
from tests.fixtures_apify import FakeActor, FakeConfiguration, FakeScraper, ok, run


class TestOptionsBeforeScraping:
    async def test_output_format_and_timeout_forwarded(self) -> None:
        actor = FakeActor(
            {"urls": ["https://example.com/a"], "timeout": 12, "output_format": "html"}
        )
        scraper = FakeScraper([ok()])
        await run(actor, scraper)

        assert scraper.calls[0][1] == {"timeout": 12, "output_format": "html"}

    async def test_apify_proxy_url_forwarded_when_enabled(self) -> None:
        actor = FakeActor(
            {"urls": ["https://example.com/a"], "proxy_config": {"use_apify_proxies": True}},
            configuration=FakeConfiguration(),
        )
        scraper = FakeScraper([ok()])
        await run(actor, scraper)

        assert scraper.calls[0][1]["proxy_url"] == "http://auto:secret@proxy.apify.com:8000"

    async def test_proxy_config_ignored_when_disabled(self) -> None:
        actor = FakeActor({"urls": ["https://example.com/a"]}, configuration=FakeConfiguration())
        scraper = FakeScraper([ok()])
        await run(actor, scraper)

        assert "proxy_url" not in scraper.calls[0][1]

    def test_missing_proxy_password_omits_proxy_url(self) -> None:
        validated = ApifyActorInput(
            urls=["https://e.com"], proxy_config={"use_apify_proxies": True}
        )

        class NoPassword:
            proxy_password = None
            proxy_hostname = "proxy.apify.com"
            proxy_port = 8000

        assert build_base_options(validated, NoPassword()) == {"timeout": 30}

    def test_no_configuration_returns_timeout_only(self) -> None:
        validated = ApifyActorInput(
            urls=["https://e.com"], proxy_config={"use_apify_proxies": True}
        )
        assert build_base_options(validated, None) == {"timeout": 30}


class TestPublicContract:
    def test_package_exports_the_documented_names(self) -> None:
        for name in ("main", "scrape_url", "ApifyActorInput", "ApifyActorOutput"):
            assert name in actor_pkg.__all__

    def test_import_does_not_require_the_apify_sdk(self) -> None:
        """The SDK is imported lazily inside the runner, never at import time."""
        assert callable(actor_pkg.main)
        assert not hasattr(actor_pkg, "Actor")

    @pytest.mark.parametrize("status", ["ok", "error", "skipped"])
    def test_status_enum_is_the_contract(self, status: str) -> None:
        item = ApifyActorOutput(url="https://e.com", status=status, scraped_at="2026-10-25")
        assert item.to_dataset_item()["status"] == status

    def test_unknown_status_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApifyActorOutput(url="https://e.com", status="bogus", scraped_at="2026-10-25")
