"""Pydantic input/output models for the Pry Apify actor.

The dataset-item contract Apify customers depend on lives here: one model per
surface, validated before any scraping starts.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ApifyProxyConfig(BaseModel):
    """Proxy configuration for the Apify actor."""

    use_apify_proxies: bool = Field(
        default=False,
        description="Use Apify-provided residential proxies",
    )
    proxy_country: str = Field(
        default="US",
        description="Country code for proxy geolocation (e.g., 'US', 'DE')",
        min_length=2,
        max_length=2,
    )


class ApifyActorInput(BaseModel):
    """Validated input for the Pry Apify actor.

    Replaces raw dict access with Pydantic validation — catches malformed
    input before any scraping starts.
    """

    urls: list[str] = Field(
        ...,
        description="List of URLs to scrape",
        min_length=1,
        max_length=1000,
    )
    max_pages: int = Field(
        default=1,
        ge=1,
        le=1000,
        description="Maximum number of pages to scrape (1-1000)",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout per URL in seconds (5-120)",
    )
    output_format: str = Field(
        default="markdown",
        description="Output format",
        pattern=r"^(markdown|html|text|json)$",
    )
    crawl: bool = Field(
        default=False,
        description="Follow same-domain links and crawl",
    )
    proxy_config: ApifyProxyConfig = Field(
        default_factory=ApifyProxyConfig,
        description="Proxy configuration",
    )
    max_depth: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum crawl depth (0-5)",
    )

    @field_validator("urls", mode="before")
    @classmethod
    def coerce_urls(cls, v: Any) -> list[str]:
        """Accept a single URL string and coerce to list."""
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("urls", mode="before")
    @classmethod
    def validate_urls(cls, v: Any) -> list[str]:
        """Strip whitespace and filter empty strings."""
        if isinstance(v, list):
            return [url.strip() for url in v if isinstance(url, str) and url.strip()]
        return v


class ApifyScrapeMetadata(BaseModel):
    """Metadata attached to a successful scrape result."""

    domain: str = Field(..., description="Scraped domain")
    content_length: int = Field(..., ge=0, description="Content length in characters")
    method: str = Field(default="unknown", description="Scraping method used")


class ApifyActorOutput(BaseModel):
    """Validated output pushed to the Apify dataset.

    T1 win #4: Structured output schema — Apify customers depend on this
    contract; Pydantic ensures every emitted item conforms.
    """

    url: str = Field(..., description="Original URL scraped")
    status: str = Field(
        ...,
        description="Result status",
        pattern=r"^(ok|error|skipped)$",
    )
    method: str = Field(default="unknown", description="Scraping method used")
    scraped_at: str = Field(..., description="ISO-8601 timestamp of scrape")
    elapsed_seconds: float = Field(default=0.0, ge=0, description="Time spent scraping")
    content: str = Field(default="", description="Scraped content (markdown/html/text)")
    raw_html: str = Field(default="", description="Raw HTML (if available)")
    error: str = Field(default="", description="Error message (if status=error)")
    metadata: ApifyScrapeMetadata = Field(
        default_factory=lambda: ApifyScrapeMetadata(
            domain="unknown", content_length=0, method="unknown"
        ),
        description="Scraping metadata",
    )

    def to_dataset_item(self) -> dict[str, Any]:
        """Convert to Apify dataset item dict (excludes None/empty fields)."""
        return self.model_dump(mode="json", exclude_none=True)
