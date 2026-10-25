"""Translation of validated actor input into scraper options."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.actors.apify_actor.models import ApifyActorInput


def build_base_options(
    validated: ApifyActorInput, configuration: Any | None = None
) -> dict[str, Any]:
    """Build per-run scraper options, including the Apify proxy URL when asked.

    Apify provides HTTP proxies via http://user:pass@proxy.apify.com:8000.
    ``Actor.config`` was removed in apify SDK 3.x, so the URL is assembled from
    ``Actor.configuration`` (proxy_hostname / proxy_port / proxy_password).
    """
    options: dict[str, Any] = {"timeout": validated.timeout}
    if not validated.proxy_config.use_apify_proxies or configuration is None:
        return options
    proxy_password = configuration.proxy_password
    if proxy_password:
        options["proxy_url"] = (
            f"http://auto:{proxy_password}"
            f"@{configuration.proxy_hostname}:{configuration.proxy_port}"
        )
    return options
