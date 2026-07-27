[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Usage Guide
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-06-30
---

# Pry Usage Guide

## Quickstart

```bash
# Install (PyPI 'pry' is taken — install from this repo)
pip install -e .
# or:
# pip install "pry-scraper @ git+https://codeberg.org/cryptorugmunch/pryscraper.git"

# Start the server
pry serve

# Scrape a URL
pry open https://example.com

# With JSON extraction
pry open https://store.com/product --json --schema product.json

# Crawl a site
pry crawl https://docs.com --max-pages 20 -o data.json
```

## Docker

```bash
docker compose up -d
# Pry on :8005 (host) → :8002 (container), FlareSolverr on :8192 (host) → :8191 (container)
```

> **Port clarification:** The API listens on container port `8002` and is published to host port `8005` (see `docker-compose.yml`). From outside the container (host machine, SDK, CLI), use `http://localhost:8005`. Use `8002` only if you `docker exec` into the running container.

## CLI Reference

| Command | Description |
|---------|-------------|
| `pry open <url>` | Scrape URL to clean markdown |
| `pry watch <url>` | Monitor page for changes |
| `pry crawl <url>` | Crawl multiple pages |
| `pry batch <file>` | Batch scrape URLs from file |
| `pry parse <url>` | Parse PDF/DOCX/image |
| `pry ss <url>` | Take screenshot |
| `pry run [pry.yml]` | Execute job file |
| `pry serve` | Start API server |
| `pry completions [bash\|zsh\|fish]` | Print shell-autocomplete install instructions |

### CLI Options

| Flag | Applies to | Description |
|------|-----------|-------------|
| `--json` | `open` | Output as JSON |
| `--schema <file>` | `open` | JSON schema file for extraction |
| `--timeout <sec>` | `open` | Request timeout |
| `--webhook <url>` | `watch` | Webhook URL for change notifications |
| `--max-pages <n>` | `crawl` | Maximum pages to crawl |
| `--template <json>` | `batch` | Extraction template as JSON string |
| `-o <file>` | `crawl`, `ss` | Output file path |
| `--port <n>` | `serve` | Server port (default: 8005) |

## API Reference

Base URL: `http://localhost:8005` (configurable via `PRY_URL` env var)

### Authentication

No authentication required for local use. For production, deploy behind a reverse proxy with auth.

### Core Endpoints

#### `POST /v1/scrape`

Scrape a single URL.

```json
{
  "url": "https://example.com",
  "bypassCloudflare": true,
  "formats": ["markdown"],
  "timeout": 30
}
```

#### `POST /v1/crawl`

Crawl multiple pages from a starting URL.

```json
{
  "url": "https://docs.com",
  "maxPages": 10,
  "maxDepth": 2,
  "timeout": 120
}
```

#### `POST /v1/extract`

Extract structured data with JSON schema.

```json
{
  "url": "https://store.com/product/123",
  "schema": {
    "name": "string",
    "price": "string",
    "description": "string",
    "availability": "string"
  }
}
```

#### `POST /v1/batch`

Scrape up to 50 URLs in parallel.

```json
{
  "urls": ["https://example1.com", "https://example2.com"],
  "bypassCloudflare": true,
  "formats": ["markdown"]
}
```

#### `POST /v1/automate`

Execute browser automation steps.

```json
{
  "steps": [
    {"action": "navigate", "url": "https://login.example.com"},
    {"action": "type", "selector": "#username", "value": "user"},
    {"action": "type", "selector": "#password", "value": "pass"},
    {"action": "click", "selector": "#login-btn"},
    {"action": "extract", "selectors": {"title": "h1"}}
  ]
}
```

#### `POST /v1/vision`

Analyze images with free OpenRouter vision models (5-model auto-fallback).

```json
{
  "url": "https://example.com/image.png",
  "question": "What is shown in this image?"
}
```

#### `POST /v1/parse`

Parse a document (PDF, DOCX, image, CSV, JSON).

```json
{
  "url": "https://example.com/document.pdf",
  "timeout": 60
}
```

#### `POST /v1/screenshot`

Take a screenshot of a URL.

```json
{
  "url": "https://example.com",
  "fullPage": true
}
```

### Monitoring Endpoints

#### `POST /v1/watch`

Register a page for change monitoring.

```json
{
  "url": "https://example.com",
  "interval": 3600,
  "webhook": "https://hooks.slack.com/..."
}
```

#### `POST /v1/monitor`

Create a scheduled monitor (cron-based).

```json
{
  "url": "https://example.com",
  "schedule": "0 */6 * * *",
  "webhook": "https://hooks.slack.com/..."
}
```

#### `POST /v1/diff`

Compare two URLs or two versions of the same page.

```json
{
  "url": "https://example.com",
  "previousSnapshot": "..."
}
```

### Export Endpoints

#### `POST /v1/export`

Export scraped content in multiple formats.

```json
{
  "data": [{ "title": "Example", "body": "..." }],
  "format": "csv",
  "options": { "filename": "export.csv" }
}
```

Supported formats: `json`, `csv` (`rss`, `txt`, `sql` listed in FEATURES.md but not yet implemented)

### Alert Endpoints

#### `POST /v1/alert/send`

Send an alert to any configured channel.

```json
{
  "channel": "slack",
  "message": "Content change detected on https://example.com",
  "webhook": "https://hooks.slack.com/..."
}
```

### GDPR / Compliance Endpoints

#### `POST /v1/compliance/check`

Run full compliance check on a URL.

```json
{
  "url": "https://example.com"
}
```

#### `POST /v1/gdpr/consent`

Record user consent.

```json
{
  "user_id": "user_123",
  "purposes": ["scraping", "storage", "analysis"],
  "consent": true
}
```

### Pipeline Endpoints

#### `POST /v1/pipelines/run`

Execute a pipeline definition.

```json
{
  "pipeline": {
    "name": "ecommerce-scraper",
    "steps": [
      {"type": "scrape", "config": {"url": "https://store.com"}},
      {"type": "extract", "config": {"schema": {"name": "string"}}},
      {"type": "export", "config": {"format": "csv"}}
    ]
  }
}
```

## Python SDK

### Async SDK

```python
from pry_sdk import PryCrawl

mc = PryCrawl("http://localhost:8005")
result = await mc.scrape("https://example.com")
print(result["data"]["markdown"])
```

### Sync SDK

```python
from pry_sdk import PryCrawlSync

mc = PryCrawlSync("http://localhost:8005")
result = mc.scrape("https://example.com")
```

### SDK Methods

| Method | Description |
|--------|-------------|
| `scrape(url, **opts)` | Scrape to markdown |
| `scrape_json(url, schema, **opts)` | Scrape with JSON extraction |
| `crawl(url, max_pages, **opts)` | Crawl site |
| `map(url, limit)` | Discover URLs |
| `parse(url)` | Parse document |
| `automate(steps, **opts)` | Browser automation |
| `screenshot(url)` | Screenshot page |
| `health()` | Service health |

## MCP (AI Agent Integration)

Compatible with Claude, Hermes, Cursor, and any MCP client.

### Tool Discovery

```
GET /mcp/tools
```

### Tool Execution

```json
POST /mcp/call
{
  "name": "pry_scrape",
  "arguments": {
    "url": "https://example.com",
    "formats": ["markdown"]
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_URL` | `http://localhost:8005` | API endpoint for CLI |
| `TOR_ENABLED` | `false` | Enable Tor routing |
| `PROXY_URL` | — | HTTP/SOCKS proxy URL |
| `RATE_LIMIT_RPM` | `120` | Requests per minute |
| `OPENROUTER_API_KEY` | — | For vision endpoint |

## Development

```bash
make install      # Install with dev deps
make dev          # Start hot-reload server
make lint         # ruff check
make format       # ruff format
make typecheck    # mypy
make test         # pytest
make check        # Full audit (lint + typecheck + test)
make security     # bandit + safety
make precommit    # ruff + mypy + bandit
```

## Browser Extension

A Chrome extension is included at `browser-extension/` for capturing pages directly from the browser.

## Platform Integrations

### WooCommerce / Shopify

```json
POST /v1/commerce/sync
{
  "platform": "shopify",
  "credentials": { "shop": "mystore.myshopify.com", "token": "..." },
  "products": [{ "title": "Example", "body_html": "...", "price": "29.99" }]
}
```

### Salesforce / HubSpot

```json
POST /v1/crm/sync
{
  "platform": "hubspot",
  "credentials": { "api_key": "..." },
  "objects": [{ "type": "contact", "data": { "email": "...", "name": "..." } }]
}
```

### Zapier / Make / Webhooks

```json
POST /v1/integrations/webhook
{
  "url": "https://hook.zapier.com/...",
  "data": { "title": "...", "body": "..." }
}
```
