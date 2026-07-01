# Pry — Open any website

Self-hosted web scraping + browser automation API. Cloudflare bypass, document parsing, AI summarization. No API keys needed.

## Quickstart

```bash
# Install
pip install pry

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
# Pry on :8002, FlareSolverr on :8191
```

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

## API

### `POST /v1/scrape`

```json
{"url": "https://example.com", "bypassCloudflare": true, "formats": ["markdown"]}
```

### `POST /v1/crawl`

```json
{"url": "https://docs.com", "maxPages": 10, "maxDepth": 2}
```

### `POST /v1/automate`

```json
{"steps": [{"action": "navigate", "url": "https://...", {"action": "click", "selector": "#btn"}]]}
```

### `POST /v1/vision`

Analyze images with free OpenRouter vision models. Auto-fallback across 5 models.

```json
{"url": "https://...", "question": "What is shown?"}
```

### `POST /v1/extract`

Extract structured data with JSON schema + optional AI fallback.

### `POST /v1/batch`

Scrape up to 50 URLs in parallel.

### `POST /v1/compare`

Diff two URLs.

### `POST /v1/summarize`

AI summarization via local Ollama (free, private).

### `GET /health`

Service health + cache stats + active sessions.

## Python SDK

```python
    from pry_sdk import PryCrawl

mc = PryCrawl("http://localhost:8002")
result = await mc.scrape("https://example.com")
print(result["data"]["markdown"])
```

```python
    from pry_sdk import PryCrawlSync

mc = PryCrawlSync("http://localhost:8002")
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

```json
POST /mcp/call
{"name": "pry_scrape", "arguments": {"url": "https://..."}}
```

Compatible with Claude, Hermes, Cursor, and any MCP client.

## Features

- **4-tier anti-detection**: Direct → FlareSolverr → Playwright → Googlebot
- **Cloudflare bypass**: Automatic via FlareSolverr
- **Document parsing**: PDF, DOCX, images (OCR), CSV, JSON
- **Browser automation**: Login flows, form filling, sessions
- **Vision AI**: Free OpenRouter vision models with auto-fallback
- **Diff tracking**: Page change monitoring with webhooks
- **Batch processing**: Parallel scrape with templates
- **SEO analysis**: Title, meta, headings, keywords, readability
- **Schema extraction**: JSON-LD, Open Graph, microdata
- **Export formats**: JSON, CSV, RSS, TXT, SQL
- **Rate limiting**: Per-IP token bucket (default 120 RPM)
- **Caching**: LRU + Redis with TTL-based invalidation
- **WebSocket streaming**: Real-time job progress
- **Circuit breaker**: Per-domain backoff on failures

## Architecture

```
┌─────────────┐  ┌──────────────┐  ┌──────────┐
│   Client    │→ │  Pry API     │→ │ Scraper  │
│ (CLI/SDK)   │  │  (FastAPI)   │  │  Engine  │
└─────────────┘  └──────┬───────┘  └────┬─────┘
                        │               ├─ Direct HTTP
                        │               ├─ FlareSolverr
                        │               ├─ Playwright
                        │               └─ Googlebot
                        │
                   ┌────┴────┐
                   │ Cache   │
                   │ Redis   │
                   │ Rate    │
                   └─────────┘
```

## Deployment

### Docker Compose (recommended)

```bash
docker compose up -d
```

### Bare metal

```bash
pip install pry
playwright install chromium
# Optional: docker run -d -p 8191:8191 ghcr.io/flaresolverr/flaresolverr
pry serve
```

### Environment

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
make check        # Full audit
```

## License

MIT — Rug Munch Media LLC
