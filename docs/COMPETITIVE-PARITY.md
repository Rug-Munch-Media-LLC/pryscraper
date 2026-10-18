# Competitive parity — scraping APIs

Status snapshot for the Pry scraping surface (`/v1/*`) against the six products we
are most often compared with. Every Pry claim below names the code path that
implements it; a capability we cannot point at is marked MISSING rather than
"planned".

- **Snapshot:** HEAD `bcd69ba6` + this change set (2026-10-18)
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
| Batch / async jobs | **F** (sync + queue-backed async) | F (batch + async) | F (runs) | P~ (batch endpoint) | F~ | P~ | P (local queue) |
| Structured extraction with schema | **F** | F (json format) | F (actors) | P~ (extract rules) | F~ (AI extract) | F~ (parse) | F |
| Screenshots | **F** (`/v1/screenshot` and `formats: ["screenshot"]`) | F (`screenshot`) | F~ | F~ | F~ | F~ | F |
| PDF: page → PDF | **F** (`formats: ["pdf"]`) | `?` (PDF *input* yes) | F~ | P~ | F~ | F~ | F (pdf) |
| PDF: PDF → text/tables | **F** (`/v1/pdf/extract`) | F | F~ | – | F~ | F~ | F |
| Proxy / anti-bot | **F** (15-tier chain, Camoufox, FlareSolverr) | F | F~ (proxy) | F~ | F~ (unlocker) | F~ | P (bring-your-own) |
| Web search endpoint | **F** (`/v1/search`, now with markdown) | F | P~ (Google actor) | – | P~ (SERP) | P~ (SERP) | – |
| Webhooks | **F** (crawl webhook + job polling) | F | F~ | P~ | F~ | P~ | – |
| Python SDK | **F** (`PryCrawl`, `PryCrawlSync`) | F | F~ | F~ | F~ | F~ | F (library) |
| TypeScript SDK | **F** (`@pryscraper/sdk`) | F | F~ (JS client) | F~ | F~ | F~ | – |
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
| Batch (async job) | SHIPPED | `POST /v1/batch` with `async: true` or `webhook` → `JobQueue`; `GET /v1/batch/{id}` in `batch_routes.py`; `tests/test_scrape_formats_extended.py` |
| Structured extraction | SHIPPED | `jsonSchema` in `scrape()`; `POST /v1/extract` (`extraction.py`) |
| Screenshot | SHIPPED | `formats: ["screenshot"]` on `/v1/scrape` → `UltimateScraper.render_media()` (pooled Chromium) via `media_formats.py`; test `test_scrape_screenshot_returns_base64_png` |
| PDF → text/tables | SHIPPED | `POST /v1/pdf/extract` (`advanced.py`) + `src/pry/engine/pdf_extractor.py` |
| Page → PDF | SHIPPED | `formats: ["pdf"]` on `/v1/scrape` → `UltimateScraper.render_media()` `page.pdf()`; test `test_scrape_pdf_returns_pdf_bytes` |
| Proxy / anti-bot | SHIPPED | `src/pry/engine/ultimate_scraper.py` tier chain; `flaresolverr.py`, `camoufox_*.py` |
| Search | SHIPPED | `POST /v1/search` (`search_map.py`) over `engine/web_search.py` (SearXNG → DDG → per-engine) |
| Webhooks | SHIPPED | `CrawlRequest.webhook` → `queue.create_job(..., webhook=...)` |
| Python SDK | SHIPPED | `src/pry/api/pry_sdk.py` (`PryCrawl`, `PryCrawlSync`), `tests/test_sdk.py` |
| TypeScript SDK | **SHIPPED** | `sdk/typescript/` — `PryClient` (`scrape`/`crawl`/`map`/`search`/`batch`/`extract`), `PryMcpClient`, typed 402/429/network errors; `sdk/typescript/test/client.test.ts` |
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

Unsupported Firecrawl formats (branding/audio/video) are ignored, not faked.
`data.metadata.formats` reports what was actually produced.

`formats: ["screenshot"]` and `["pdf"]` render through the engine browser hook
(`UltimateScraper.render_media`, reusing the process-wide `BrowserPool`) and
return base64 in `data.screenshot` / `data.pdf`. Caps are 10 MiB PNG and 20 MiB
PDF; a render over the cap fails with `422 scrape_failed`. The render budget is
the request `timeout`, clamped to 60s. Media responses are never written to the
shared response cache.

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

### 3. Async `/v1/batch` on the existing job queue

Before: `/v1/batch` was synchronous only. After: a Firecrawl object body with
`async: true` (or a `webhook`) creates a `batch` job on the same `JobQueue` the
crawl path uses, returns its id, and `GET /v1/batch/{id}` reports
`queued`/`scraping`/`completed`/`failed` plus per-URL pages. The legacy JSON
array body and the sync response are unchanged; nothing else creates a second
store.

Tests: `tests/test_parity_wins.py` (9 tests) — formats, cache identity, map
filters, sitemap-only, ignore-sitemap, search scrapeOptions, source rejection.
`tests/test_scrape_formats_extended.py` (9 tests) — screenshot/PDF base64,
size caps, no render when media is not requested, sync batch unchanged, async
job id + webhook, job completion, unknown-job 404.

Structured extraction note: Pry has no `formats: ["extract"]` keyword. Schema
extraction is the `jsonSchema` field on `/v1/scrape` (v1 shape), verified by
`tests/test_api_scraping.py::test_v1_scrape_with_json_schema`; `POST /v1/extract`
covers rule-based extraction.

## Recommended next 10 gaps (value ÷ effort, highest first)

The previous top 3 (screenshot format, page→PDF, async batch) shipped
2026-10-18 — see the wins above. Remaining gaps, re-ranked:

| # | Gap | Why it matters | Effort |
|---|---|---|---|
| 1 | TypeScript SDK | Half the AI-agent ecosystem is TS; Python-only loses them at hello-world | M |
| 2 | `includePaths` / `excludePaths` / `limit` on `/v1/crawl` | Firecrawl crawl tuning; needs the filter inside `scraper.crawl`, not a post-filter | M |
| 3 | `formats: ["json"]` inline in `formats` (schema object) | Firecrawl v2 moved schema into `formats`; our `jsonSchema` field is v1-shaped | S |
| 4 | `maxAge` / `storeInCache` cache controls | We cache, but callers cannot force freshness — a correctness complaint waiting to happen | S |
| 5 | `location` (country/languages) + proxy selection | Geo-targeted SERP and price pages; proxy pool exists, no selector | M |
| 6 | `actions` (wait/click/write) before scrape | Login-walled and lazy-loaded pages; Playwright path exists | M |
| 7 | Per-key usage dashboard API (`/v1/usage` breakdown by endpoint) | Observability exists internally; customers cannot self-serve quotas | S |

## Caveats / non-claims

- We do **not** have `branding`, `product`, `audio`, `video`, `query`,
  `highlights` or `rawBase64` formats. Unknown format names are ignored.
- `/v1/batch` is capped at 50 URLs. The sync path stays sync; `async: true` /
  `webhook` uses the in-process `JobQueue` (Redis-backed with a local fallback),
  not a separate worker fleet.
- Screenshot/PDF are scrape formats now, but there is no `screenshot@fullPage`
  flag: screenshots are always full-page, PDFs always A4 with backgrounds.
- `formats: ["extract"]` is not accepted; schema extraction remains `jsonSchema`.
- No TypeScript SDK; no hosted dashboard parity claim beyond Prometheus/OTel.
