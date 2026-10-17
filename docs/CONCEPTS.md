# Concepts

Five objects explain Pry: the page, the tier chain, the payment challenge, the actor, and the template. The MCP server wraps all of them.

## The request path

```
 client  (curl / CLI / MCP tool / SDK)
    │
    │ POST /v1/scrape  {"url": "...", "jsRender": false}
    ▼
 ┌──────────────┐   unpaid    ┌──────────────────────────────┐
 │ auth + x402  │────────────▶│ 402  accepts[]: network,     │
 │    gate      │             │ asset, maxAmountRequired,    │
 └──────┬───────┘             │ payToAddress                 │
        │ paid / no gate      └──────────────┬───────────────┘
        ▼                                    │ client pays on-chain
 ┌──────────────┐                            │ and retries with
 │  tier chain  │◀───────────────────────────┘ PAYMENT-SIGNATURE
 │  1 → 15      │
 └──────┬───────┘
        │ first tier that returns real content
        ▼
 ┌──────────────┐
 │  markdown /  │──▶ response  {"success": true, "data": {...}}
 │     JSON     │──▶ per-domain memory: remember the winning tier
 └──────────────┘
```

Code: `src/pry/api/routers/scraping/scraping.py` (route), `src/pry/engine/scraper_orchestrate.py` (tier loop), `src/pry/payments/x402/` (gate).

## Page

A page is one URL fetched once. The response is `data.markdown` plus `data.metadata`:

```json
{"success": true,
 "data": {"markdown": "...", "metadata": {"url": "...", "method": "direct", "title": "...", "offset": 0, "total": 1256}}}
```

`metadata.method` is the tier that served it. `offset` and `limit` page through the Markdown; `total` is its full length. Pass `jsonSchema` to add `data.json`; pass `formats` to ask for other representations (`ScrapeRequest`, `scraping_models.py`).

`metadata.markdown_quality` is a 0-100 score of that Markdown, with the per-check detail in `metadata.markdown_checks`. Seven weighted checks run: relative links, fenced-code languages, heading structure, stray HTML tables, images, boilerplate noise, and duplicate blocks (`src/pry/engine/markdown_quality.py`). A low score means the page yielded little readable content, so escalate the tier or switch to extraction.

## Search and map

Two routes answer questions that are not "fetch this page":

- `POST /v1/search` returns ranked web results. Send `{"query": "...", "limit": 5}`; read `data.results[]` with `url`, `title`, and `description`. SearXNG is the first engine, DuckDuckGo the fallback. Limit is 1-20.
- `POST /v1/map` returns same-origin URLs for a site. Send `{"url": "...", "limit": 50}`; read `data.links`. It reads `sitemap.xml` when `ignoreSitemap` is false and falls back to link extraction. Limit is 1-500.

Both validate every URL through the SSRF guard and both carry an x402 price (`search_map.py`).

## Async jobs

`POST /v1/crawl` is synchronous unless the body carries a `webhook`. With one, the call returns `{"success": true, "data": {"id": "<job_id>", "status": "pending"}}` and the crawl continues in the background.

Poll `GET /v1/crawl/{id}` for the job record, or let the webhook deliver it. `DELETE /v1/crawl/{id}` cancels a queued or running job and returns the final status; repeating it is idempotent. `GET /v1/crawl/{id}/errors` lists per-URL failures (`crawl_jobs.py`).

## Tiers

A tier is one way to fetch a page. The engine starts cheap and escalates only on failure. There are 15, defined as `_tier_*` methods:

```
direct → tls_fingerprint → cloudscraper → flaresolverr → undetected →
camoufox → playwright → googlebot → tor → premium_proxy → archive →
google_cache → ai_visual → mobile_app → graphql
```

The engine records the winning tier per domain (`src/pry/engine/resilience.py`) and ranks candidates next time (`tier_score.py`). This is why the same URL is usually faster on the second call.

## Markdown and JSON

`markdown` is the default output: boilerplate stripped, main content kept. For typed output, send `fields` to `POST /v1/extract`:

```json
{"url": "https://shop.example/p/1",
 "fields": {"product_name": "Name of the product", "price": "Price in USD"}}
```

The LLM fills the keys and returns them under `data`. For a fixed page shape, prefer a template: it uses stored CSS selectors and costs less than an LLM call.

## x402

x402 is HTTP 402 with a machine-readable price. An unpaid request is not an error; it is a quote.

1. Server returns `402` with `accepts[]`: `network` (CAIP-2), `asset`, `maxAmountRequired` (atomic units), `payToAddress`.
2. Client pays that amount on that chain.
3. Client retries the same request with `PAYMENT-SIGNATURE`.
4. Server verifies settlement and returns the data.

No account is created and no subscription is signed; the wallet is the identity. Seven networks settle: Base, Ethereum, Arbitrum, Optimism, Polygon, Solana, TRON (`SUPPORTED_NETWORKS`, `src/pry/payments/x402/scheme/networks.py`). Prices live in `X402_PRICING` (`.../pricing/catalog.py`) and are visible at `GET /v1/x402/pricing`.

Self-hosting sets `PRY_X402_ENABLED=false`: the middleware is never constructed, so no request returns 402.

## Actor

An actor is a packaged scraper for the Apify platform. Each directory under `actor_factory/actors/` holds `.actor/actor.json`, an input schema, and `src/main.py`. Actors call the same engine; they exist so the same job can run on Apify's runtime. There are 112.

## Template

A template is a stored page recipe: a site, a base selector, and typed fields. Files live in `src/pry/commerce/templates/*.json` (110 of them). Execute one with `POST /v1/templates/execute`:

```json
{"template_id": "amazon_product", "url": "https://www.amazon.com/dp/..."}
```

Templates are deterministic and cheaper than LLM extraction. Use one when the site is already covered; use `/v1/extract` when it is not.

## MCP server

The MCP server is the same API with tool schemas. It is mounted at `/mcp/` (Streamable HTTP) with an SSE endpoint at `/mcp/sse`, and is also available over stdio as `pry-mcp`.

- 99 tools in 33 categories (`pry_mcp/tools/`).
- Each tool maps to a REST route in `pry_mcp/tool_routes.py`.
- Discovery (`tools/list`) needs no key. `tools/call` needs an API key or an x402 payment.

An MCP client therefore sees the same page, tiers, and prices as a curl user; only the envelope differs (JSON-RPC instead of HTTP).
