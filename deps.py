"""Shared global instances for Pry API.

This module initializes the singleton instances used by all API routers
and should be imported by both api.py and any router module that needs
direct access to shared state.

Usage:
    from deps import scraper, cache, automator, ...
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from advanced import PryAdvanced
from automator import PryAutomator
from cache import ResponseCache
from extractor import SchemaExtractor
from jobqueue import JobQueue
from parser import DocumentParser
from ratelimit import RateLimiter
from scraper import PryScraper
from settings import settings
from user_ratelimit import user_ratelimiter

scraper = PryScraper()
automator = PryAutomator()
parser = DocumentParser()
extractor = SchemaExtractor()
cache = ResponseCache(capacity=1000)
# Redis-backed when settings.redis_url is reachable; per-process token bucket
# otherwise (see ratelimit.py — backend failures degrade, never block).
ratelimiter = RateLimiter(
    default_rpm=settings.rate_limit_rpm, burst=200, redis_url=settings.redis_url
)
queue = JobQueue()
advanced = PryAdvanced(cache=cache)
user_ratelimiter = user_ratelimiter
