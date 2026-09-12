#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
# Build and deploy Pry (quick test)
set -e

echo "=== Installing deps ==="
cd /path/to/pry
pip install -q fastapi uvicorn trafilatura httpx markdownify pydantic 2>&1 | tail -3

echo "=== Testing import ==="
python3 -c "from scraper import PryScraper; print('PryScraper: OK')"

echo "=== Testing API import ==="
python3 -c "from api import app; print('API: OK')"

echo "=== Quick scrape test ==="
python3 -c "
import asyncio
from scraper import PryScraper
async def test():
    s = PryScraper()
    r = await s.scrape('https://example.com')
    print(f'Status: {r[\"status\"]}')
    print(f'Method: {r[\"method\"]}')
    print(f'Content ({len(r.get(\"content\",\"\"))} chars): {r.get(\"content\",\"\")[:200]}')
asyncio.run(test())
"

echo ""
echo "=== ALL GOOD ==="
