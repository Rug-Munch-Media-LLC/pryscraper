# Pry RDAP Domain Watch

Track domain registration data via the public RDAP protocol - expiry dates, status flags and nameservers for portfolio management, expiry sniping and brand protection.

> Need **rdap domain watch data** without infrastructure headaches? This actor scrapes, monitors and exports it on Apify's managed runtime - pay per result, no subscription.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **1 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Use Cases

- **Continuous monitoring** - schedule the actor to pull fresh rdap domain watch data on the cadence you need (hourly, daily, weekly) and alert via webhooks when anything changes
- **Market & competitive research** - bulk-collect rdap domain watch records into one dataset to benchmark competitors, prices and trends over time
- **AI & analytics pipelines** - export clean, structured domain checked results to JSON/CSV/Excel, or feed them straight into LLM/RAG workflows, BI dashboards or a warehouse via the Apify API
## Tutorial

1. Paste the API endpoint(s) you want tracked into `urls` - the README's *Data source* section shows the exact URL pattern.
2. Set `data_path` if the array you want lives deeper in the payload (e.g. `data.items`).
3. Hit **Start** - JSON responses come back as clean dataset records; non-JSON replies are flagged, not buried.
4. Schedule it or wire a webhook - exports work as JSON/CSV/Excel or straight via API.

## Pricing

### How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0005` per `domain-checked` (one domain's rdap record pulled.) - that is **$0.50 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 512 MB costs roughly **$0.05** in event charges (platform compute adds about $0.0333). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `domain-checked` | Domain checked | $0.0005 | One domain's RDAP record pulled. |

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
        "ldhName": "EXAMPLE.COM",
        "status[0]": "active",
        "events[0].eventAction": "expiration",
        "events[0].eventDate": "2027-01-01T00:00:00Z"
      }
    ],
    "count": 1,
    "total_in_response": 25
  }
}
```

### Dataset fields

- `url` - the source URL that produced this item
- `status` - `ok`, `skipped` or `error`, so downstream jobs can filter reliably
- `method` - which tier of the fallback chain succeeded (transparency into how the data was fetched)
- `scraped_at` - ISO-8601 UTC timestamp for time-series use
- `data` / `content` - the extracted payload (structured records or clean markdown, depending on the actor)

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## Data source

This Actor reads **RDAP bootstrap protocol (registration data access)** - a documented public API. No scraping fragility, no anti-bot lottery: the data you get is the data the source publishes.

**URL pattern** (paste your own targets):

```
https://rdap.org/domain/<DOMAIN>
```

API reference: https://about.rdap.org

## How can I use this data?

- **Market research** - track domain checked trends across competitors
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

## Limitations

- Sources must return JSON (or JSON inside HTML) - binary or pure-HTML endpoints are reported as `skipped`, not guessed
- Free/public API tiers apply their own rate limits; very large batches may need scheduling across runs
- Authentication-protected endpoints need publicly reachable URLs - private dashboards are out of scope

## Troubleshooting

- **Empty dataset?** Check the run log - each URL is reported with `ok`, `skipped` or `error` and a reason; fix the flagged targets and re-run
- **Blocked or 403 responses?** The adaptive ladder escalates automatically; if a target still fails, lower `max_items` and retry later, or schedule runs further apart
- **Unexpected fields?** Compare your output against the example below - `data_path` (where present) controls which array is extracted
- **Run stopped early?** You hit the spending limit or `max_items` cap - raise the cap and resume; completed items are always flushed to the dataset

## FAQ

**What exactly does Pry RDAP Domain Watch deliver?** Track domain registration data via the public RDAP protocol - expiry dates, status flags and nameservers for portfolio management, expiry sniping and brand protection. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**How reliable is this data source?** This Actor reads a documented public API or feed - the same data you would get querying it yourself, without scraping fragility. No anti-bot lottery, no silent breakage.

**The response is not JSON - what happened?** Items arrive with status 'skipped' and the parse error in the error field, so you can see exactly which URLs need attention instead of guessing from empty results.

## Support

Issues and feature requests: [repository](https://codeberg.org/RugMunchMedia/pryscraper). Custom actors built on this engine are available on request.
