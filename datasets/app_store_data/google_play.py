"""Google Play store data — scraped from play.google.com (no API key).

Backed by public store pages:

* Search — ``https://play.google.com/store/search?c=apps`` with the app
  results embedded in ``__NEXT_DATA__`` (and legacy ``AF_initDataCallback``
  blocks). We parse the embedded JSON rather than the DOM.
* Details — ``https://play.google.com/store/apps/details?id={package}``,
  same embedded-JSON approach.
* Reviews — ``https://play.google.com/store/getreviews`` POST, which
  returns JSON prefixed with a ``)]}'`` magic string.

Google does not document these endpoints and may serve a captcha /
anti-bot page to datacenter IPs. When that happens we **flag** it
(setting :data:`last_anti_bot` and logging a warning) and degrade to
``[]`` / ``{}`` — we never raise.

Contract
--------
* :func:`search_apps` — async, never raises, returns a ``list`` (``[]``
  on failure). Keyword search across Play apps (US store, English).
* :func:`get_app_details` — async, never raises, returns a ``dict``
  (``{}`` on failure). Details for a package id.
* :func:`get_reviews` — async, never raises, returns a ``list`` (``[]``
  on failure). Most recent reviews for a package.

Result shapes
-------------
``search_apps`` returns a list of::

    {
        "package": "com.instagram.android", "title": "Instagram",
        "developer": "Instagram", "genre": "Social",
        "rating": 4.0, "rating_count": 16253401, "price": "",
        "url": "https://play.google.com/store/apps/details?id=com.instagram.android",
    }

``get_app_details`` returns the same base fields plus ``summary``,
``description``, ``installs``, ``size``, ``version``, ``updated`` and
``contains_ads``. ``{}`` when the package is unknown.

``get_reviews`` returns a list of::

    {"author": "PlayUser42", "rating": 5, "title": "",
     "body": "Works great", "date": "August 15, 2026", "version": "330.0.0"}

Notes
-----
* ``price`` is empty for free apps; paid apps carry the storefront string
  (e.g. ``"$2.99"``) or a formatted value derived from ``priceValue``.
* Anti-bot detection is best-effort; a captcha page that happens to
  contain app-shaped JSON could be parsed as a stale/cached result.

Implementation is split across ``google_play_common`` (constants,
mappers, extractors), ``google_play_parsers`` (record mappers) and
``google_play_fetchers`` (HTTP transport + public API); this module is
the facade and owns the mutable anti-bot flag and retry config.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import httpx

from datasets.app_store_data.google_play_fetchers import (
    get_app_details,
    get_reviews,
    search_apps,
)
from pry.engine.retry import RetryConfig

#: Set to True when the last Play request was answered with an anti-bot page.
last_anti_bot: bool = False

_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError, OSError),
)

__all__ = ["get_app_details", "get_reviews", "last_anti_bot", "search_apps"]
