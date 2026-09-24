"""OFAC download transport with source fallback and retry control."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from datasets.legal_docs.sanctions.entries import (
    _parse_csv_entries,
    _parse_json_entries,
    _parse_xml_entries,
)
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)
_SDN_JSON_URL = "https://www.treasury.gov/ofac/downloads/sdn.json"
_SDN_XML_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
_SDN_CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json,text/xml,text/csv,*/*;q=0.8",
}


async def _http_text(url: str) -> str | None:
    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        logger.debug("legal_ofac_fetch_failed", exc_info=True, extra={"url": url})
        return None


async def _fetch_entries_network() -> list[dict[str, Any]] | None:
    raw = await _http_text(_SDN_JSON_URL)
    if raw:
        try:
            parsed = _parse_json_entries(json.loads(raw))
        except json.JSONDecodeError:
            logger.debug("legal_ofac_json_parse_failed", exc_info=True)
            parsed = None
        if parsed:
            logger.info("legal_ofac_source_json")
            return parsed
    raw = await _http_text(_SDN_XML_URL)
    if raw:
        parsed = _parse_xml_entries(raw)
        if parsed:
            logger.info("legal_ofac_source_xml")
            return parsed
    raw = await _http_text(_SDN_CSV_URL)
    if raw:
        parsed = _parse_csv_entries(raw)
        if parsed:
            logger.info("legal_ofac_source_csv")
            return parsed
    return None


def configure_retries(config: RetryConfig) -> RetryConfig:
    """Replace the OFAC retry policy and return the previous policy."""
    global _RETRY_CONFIG
    previous, _RETRY_CONFIG = _RETRY_CONFIG, config
    return previous
