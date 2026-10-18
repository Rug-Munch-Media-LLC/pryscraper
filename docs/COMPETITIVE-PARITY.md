# Competitive parity — scraping APIs

Status snapshot for the Pry scraping surface (`/v1/*`) against the six products we
are most often compared with. Every Pry claim below names the code path that
implements it; a capability we cannot point at is marked MISSING rather than
"planned".

- **Snapshot:** HEAD `68272fd7` + this change set (2026-10-18)
- **Vendors:** Firecrawl, Apify, ScrapingBee, Bright Data, Oxylabs, Crawl4AI
- **Sources (retrieved 2026-10-18):**
  - Firecrawl scrape/formats — <https://docs.firecrawl.dev/features/scrape>
  - Firecrawl pricing — <https://www.firecrawl.dev/pricing>
  - Crawl4AI docs — <https://docs.crawl4ai.com/>
  - Crawl4AI (self-hosted crawler) — <https://crawl4ai.org/>
  - Apify platform docs — <https://docs.apify.com/platform/actors>
  - ScrapingBee API docs — <https://www.scrapingbee.com/documentation/>
  - Bright Data Web Unlocker/Scraping Browser — <https://docs.brightdata.com/>
  - Oxylabs Web Scraper API — <https://developers.oxylabs.io/scraping-solutions/web-scraper-api>

**Method + confidence.** Firecrawl and Crawl4AI rows were checked against live
pages this session. Apify / ScrapingBee / Bright Data / Oxylabs cells are read
from their public documentation and marked `~` where the exact tier/plan matters
— treat those as directional, not contractual. Pry cells are all code-verified.

Legend: **F** full · **P** partial · **–** absent · **~** vendor-doc claim, not
re-fetched · `?` unknown.

## Matrix

| Capability | Pry | Firecrawl | Apify | ScrapingBee | Bright Data | Oxylabs | Crawl4AI |
|---|---|---|---|---|---|---|---|
| Single-page scrape → markdown | **F** | F | F~ | F~ | F~ | F~ | F |
| JS rendering | **F** | F | F~ | F~ | F~ | F~ | F |
| Crawl (multi-page) | **F** | F | F~ (Crawler) | P~ (no crawl) | F~ | P~ | F |
| Site map / URL discovery | **F** | F | P~ (sitemap actor) | – | P~ | – | P (link extract) |
| Batch / async jobs | **P** | F (batch + async) | F (runs) | P~ (batch endpoint) | F~ | P~ | P (local queue) |
| Structured extraction with schema | **F** | F (json format) | F (actors) | P~ (extract rules) | F~ (AI extract) | F~ (parse) | F |
| Screenshots | **P** (`/v1/screenshot`, not a scrape format) | F (`screenshot`) | F~ | F~ | F~ | F~ | F |
| PDF: page → PDF | **–** | `?` (PDF *input* yes) | F~ | P~ | F~ | F~ | F (pdf) |
| PDF: PDF → text/tables | **F** (`/v1/pdf/extract`) | F | F~ | – | F~ | F~ | F |
| Proxy / anti-bot | **F** (15-tier chain, Camoufox, FlareSolverr) | F | F~ (proxy) | F~ | F~ (unlocker) | F~ | P (bring-your-own) |
| Web search endpoint | **F** (`/v1/search`, now with markdown) | F | P~ (Google actor) | – | P~ (SERP) | P~ (SERP) | – |
| Webhooks | **F** (crawl webhook + job polling) | F | F~ | P~ | F~ | P~ | – |
| Python SDK | **F** (`PryCrawl`, `PryCrawlSync`) | F | F~ | F~ | F~ | F~ | F (library) |
| TypeScript SDK | **–** | F | F~ (JS client) | F~ | F~ | F~ | – |
| MCP server | **F** (`pry_mcp/`) | F | P~ | – | – | – | P (community) |
| Self-host | **F** (`docker-compose.selfhost.yml`) | F (OSS) | – | – | – | – | F |
| Pricing model | **x402 per call + tiers** | credits | compute units | credits | GB/plan~ | credits~ | free (self-host) |
| Rate-limit signalling | **F** (`x-ratelimit-*` headers) | F | F~ | F~ | F~ | F~ | – (local) |
| Observability | **F** (Prometheus + OTel + audit) | P~ (dashboard) | F~ | P~ | F~ | F~ | P (logs) |

## Pry evidence (every SHIPPED / PARTIAL row)

| Capability | Status | Proof |
|---|---|---|
| Single-page scrape | SHIPPED | `POST /v1/scrape` — `src/pry/api/routers/scraping/scraping.py` `scrape()` |
| JS rendering | SHIPPED | `jsRender` → `scraper.scrape(..., {"js_render": ...})`; browser tiers in `src/pry/engine/` (camoufox/playwright) |
| Crawl | SHIPPED | `POST /v1/crawl` (`crawl()`), depth/page caps in `CrawlRequest` |
| Async crawl jobs | SHIPPED | `src/pry/api/routers/scraping/crawl_jobs.py` — `GET/DELETE /v1/crawl/{id}`, `/errors` |
| Site map | SHIPPED | `POST /v1/map` — `search_map.py` `map_site()`; sitemap → crawl fallback |
| Batch (sync) | SHIPPED | `POST /v1/batch` — `batch_scrape()`, max 50 URLs |
| Batch (async job) | **PARTIAL** | only crawl is queue-backed; `/v1/batch` is synchronous |
| Structured extraction | SHIPPED | `jsonSchema` in `scrape()`; `POST /v1/extract` (`extraction.py`) |
| Screenshot | **PARTIAL** | `POST /v1/screenshot` in `src/pry/api/routers/core/automation.py`; not accepted as `formats: ["screenshot"]` on `/v1/scrape` |
| PDF → text/tables | SHIPPED | `POST /v1/pdf/extract` (`advanced.py`) + `src/pry/engine/pdf_extractor.py` |
| Page → PDF | **MISSING** | no route generates a PDF from a URL |
| Proxy / anti-bot | SHIPPED | `src/pry/engine/ultimate_scraper.py` tier chain; `flaresolverr.py`, `camoufox_*.py` |
| Search | SHIPPED | `POST /v1/search` (`search_map.py`) over `engine/web_search.py` (SearXNG → DDG → per-engine) |
| Webhooks | SHIPPED | `CrawlRequest.webhook` → `queue.create_job(..., webhook=...)` |
| Python SDK | SHIPPED | `src/pry/api/pry_sdk.py` (`PryCrawl`, `PryCrawlSync`), `tests/test_sdk.py` |
| TypeScript SDK | **MISSING** | no TS client in the tree (`browser-extension/`, `wordpress-plugin/` are not SDKs) |
| MCP server | SHIPPED | `pry_mcp/` + `pulsemcp.json`, `server.json`, `glama.json` |
| Self-host | SHIPPED | `docker-compose.selfhost.yml`, `Dockerfile`, `docker-entrypoint.sh` |
| Pricing | SHIPPED | `src/pry/payments/x402_middleware/config.py` (`X402_PRICING`, `PAID_ENDPOINTS`); tier limits in `src/pry/core/api_keys_service.py` |
| Rate-limit headers | SHIPPED | `src/pry/core/middleware_http.py` `_send_with_headers()`; values from `middleware_ratelimit.py` |
| Observability | SHIPPED | `src/pry/core/observability.py` (Prometheus), `otel/`, `src/pry/core/audit.py` |

## Wins implemented in this change

### 1. `/v1/scrape` honours `formats` (markdown, html, rawHtml, links, images)

Before: `formats` was accepted and sent to the engine, then dropped — the response
was always markdown only. After: `_requested_formats()` normalises the list,
`_format_extras()` parses the HTML once and returns `html` (readability-cleaned,
falling back to source), `rawHtml`, `links` (absolute, deduped, max 1000) and
`images`. `formats` is also part of the cache key, so a markdown-only cache entry
can never satisfy a `links` request.

Unsupported Firecrawl formats (screenshot/branding/audio/video) are ignored, not
faked. `data.metadata.formats` reports what was actually produced.

### 2. `/v1/map` applies `search`, `ignoreSitemap`, `sitemapOnly`

Before: `search` and `ignoreSitemap` were declared on the model and silently
ignored — every call read the sitemap and returned unfiltered links. After:
`search` filters URLs case-insensitively, `ignoreSitemap: true` skips the sitemap
fetch entirely (no wasted request), and `sitemapOnly: true` suppresses the crawl
fallback. `ignoreSitemap` default is now `false`, which matches the behaviour
clients already observed (sitemap first) and Firecrawl's default.

### 3. `/v1/search` accepts `scrapeOptions.formats: ["markdown"]`

Before: search returned titles/snippets only, even though
`engine/web_search_pipeline.search_and_scrape()` already existed. After: the
route delegates to that engine when markdown is requested and returns
`markdown` per hit (Firecrawl `/search` + `scrapeOptions` parity). `sources` is
validated: only `web` is implemented, so `news`/`images` return **400** instead
of being silently ignored.

Tests: `tests/test_parity_wins.py` (9 tests) — formats, cache identity, map
filters, sitemap-only, ignore-sitemap, search scrapeOptions, source rejection.

## Recommended next 10 gaps (value ÷ effort, highest first)

| # | Gap | Why it matters | Effort |
|---|---|---|---|
| 1 | `formats: ["screenshot"]` on `/v1/scrape` | Screenshot is the #1 Firecrawl migration blocker; engine already drives a browser (`/v1/screenshot` proves it) | S |
| 2 | Page → PDF (`formats: ["pdf"]`) | Every paid competitor sells it; one `page.pdf()` call on the existing browser path | S |
| 3 | Async `/v1/batch` + `GET /v1/batch/{id}` | Large migrations batch 100s of URLs; only crawl is queue-backed today | M |
| 4 | TypeScript SDK | Half the AI-agent ecosystem is TS; Python-only loses them at hello-world | M |
| 5 | `includePaths` / `excludePaths` / `limit` on `/v1/crawl` | Firecrawl crawl tuning; needs the filter inside `scraper.crawl`, not a post-filter | M |
| 6 | `formats: ["json"]` inline in `formats` (schema object) | Firecrawl v2 moved schema into `formats`; our `jsonSchema` field is v1-shaped | S |
| 7 | `maxAge` / `storeInCache` cache controls | We cache, but callers cannot force freshness — a correctness complaint waiting to happen | S |
| 8 | `location` (country/languages) + proxy selection | Geo-targeted SERP and price pages; proxy pool exists, no selector | M |
| 9 | `actions` (wait/click/write) before scrape | Login-walled and lazy-loaded pages; Playwright path exists | M |
| 10 | Per-key usage dashboard API (`/v1/usage` breakdown by endpoint) | Observability exists internally; customers cannot self-serve quotas | S |

## Caveats / non-claims

- We do **not** have `branding`, `product`, `audio`, `video`, `query`,
  `highlights` or `rawBase64` formats. Unknown format names are ignored.
- `/v1/batch` is synchronous and capped at 50 URLs; it is not a job.
- Screenshot and PDF are separate routes, not scrape formats (see gaps 1–2).
- No TypeScript SDK; no hosted dashboard parity claim beyond Prometheus/OTel.
