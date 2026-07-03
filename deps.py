"""Shared global instances for Pry API.

This module initializes the singleton instances used by all API routers
and should be imported by both api.py and any router module that needs
direct access to shared state.

Usage:
    from deps import scraper, cache, automator, ...

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from advanced import PryAdvanced
from automator import PryAutomator
from cache import ResponseCache
from extractor import SchemaExtractor
from jobqueue import JobQueue
from mconfig import PryConfig
from parser import DocumentParser
from ratelimit import RateLimiter
from scraper import PryScraper

config = PryConfig()

scraper = PryScraper()
automator = PryAutomator()
parser = DocumentParser()
extractor = SchemaExtractor()
cache = ResponseCache(capacity=1000)
ratelimiter = RateLimiter(default_rpm=120, burst=200)
queue = JobQueue()
advanced = PryAdvanced(cache=cache)
