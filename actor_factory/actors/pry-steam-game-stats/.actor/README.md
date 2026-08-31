# Pry Steam Game Stats

Game details, pricing and player counts pulled from Steam's public store API - release data, genres and concurrent-player context for market research and gaming analytics.

> Looking to **steam data at scale**, need a reliable **steam scraper**, or want **steam monitoring** without infrastructure headaches? This actor handles it on Apify's managed runtime.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **1 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Tutorial

1. Paste the API endpoint(s) you want tracked into `urls` - the README's *Data source* section shows the exact URL pattern.
2. Set `data_path` if the array you want lives deeper in the payload (e.g. `data.items`).
3. Hit **Start** - JSON responses come back as clean dataset records; non-JSON replies are flagged, not buried.
4. Schedule it or wire a webhook - exports work as JSON/CSV/Excel or straight via API.

## How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0005` per `game-stats-pulled` (one game stats record pulled.) - that is **$0.50 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 512 MB costs roughly **$0.05** in event charges (platform compute adds about $0.0333). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `game-stats-pulled` | Game stats pulled | $0.0005 | One game stats record pulled. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://example.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "data": {
    "records": [
      {
        "objectID": "41000001",
        "title": "Show HN: example",
        "points": 128,
        "num_comments": 44
      }
    ],
    "count": 1,
    "total_in_response": 25
  }
}
```

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## Data source

This Actor reads documented public JSON APIs. Paste any endpoint returning JSON as a target URL - responses are parsed into clean dataset records with honest skip-reporting for non-JSON replies.

## How can I use this data?

- **Market research** - track game stats pulled trends across competitors
- **Alerting** - pair with Apify schedules + webhooks for real-time notifications
- **AI pipelines** - dataset exports feed directly into LLM/RAG workflows
- **Reporting** - export to JSON/CSV/Excel or consume via the Apify API in your own tools

## More actors

This actor is part of the [actor family](https://apify.com/cryptorugmuncher) - 50+ scrapers, crawlers and monitors covering SERP, maps leads, LLM corpora, compliance monitoring and dark-web sources. Same engine, same reliability, one subscription-free billing model.

## Using this Actor with the Apify API

Run it programmatically:

```bash
curl -X POST https://api.apify.com/v2/acts/~run \\
  -H "Authorization: Bearer $APIFY_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"urls": ["https://example.com"]}'
```

Integrations: Zapier, Make, n8n, Airbyte and webhooks are first-class on the Apify platform.

## FAQ

**What exactly does Pry Steam Game Stats deliver?** Game details, pricing and player counts pulled from Steam's public store API - release data, genres and concurrent-player context for market research and gaming analytics. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**How reliable is this data source?** This Actor reads a documented public API or feed - the same data you would get querying it yourself, without scraping fragility. No anti-bot lottery, no silent breakage.

**The response is not JSON - what happened?** Items arrive with status 'skipped' and the parse error in the error field, so you can see exactly which URLs need attention instead of guessing from empty results.

## Support

Issues and feature requests: [repository](https://github.com/cryptorugmuncher/pryscraper). Custom actors built on this engine are available on request.
