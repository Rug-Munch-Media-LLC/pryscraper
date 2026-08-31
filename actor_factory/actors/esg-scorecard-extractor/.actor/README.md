# Pry ESG Scorecard Extractor

Extract ESG and sustainability metrics from corporate report pages and PDFs - emissions figures, diversity ratios, governance scores - each metric extracted into structured rows for compliance reporting.

> Need **esg scorecard extractor data** without infrastructure headaches? This actor scrapes, monitors and exports it on Apify's managed runtime - pay per result, no subscription.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **2 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Use Cases

- **Continuous monitoring** - schedule the actor to pull fresh esg scorecard extractor data on the cadence you need (hourly, daily, weekly) and alert via webhooks when anything changes
- **Market & competitive research** - bulk-collect esg scorecard extractor records into one dataset to benchmark competitors, prices and trends over time
- **AI & analytics pipelines** - export clean, structured metric extracted results to JSON/CSV/Excel, or feed them straight into LLM/RAG workflows, BI dashboards or a warehouse via the Apify API
## Tutorial

1. Point `urls` at the pages carrying the structured data (product pages, recipe posts, FAQ centers...).
2. Keep defaults or narrow the entity types to extract.
3. Click **Start** - entities stream in as typed, flattened records; pages without matching data report as skipped.
4. Export via dataset UI, API, or webhook.

## Pricing

### How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0300` per `metric-extracted` (one esg metric extracted with value, unit and source.) - that is **$30.00 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 1024 MB costs roughly **$3.00** in event charges (platform compute adds about $0.0667). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `metric-extracted` | Metric extracted | $0.0300 | One ESG metric extracted with value, unit and source. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `pdf_fallback` | boolean | no | Parse linked sustainability-report PDFs with OCR fallback. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://example.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "extracted": {
    "entities": [
      {
        "type": "Product",
        "fields": {
          "name": "Wool Runner",
          "brand": "Example",
          "offers.price": "98.00",
          "offers.priceCurrency": "USD",
          "offers.availability": "InStock"
        }
      }
    ]
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

## How can I use this data?

- **Market research** - track metric extracted trends across competitors
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

- Publicly accessible pages only - login-walled or paywalled content is not supported
- Extremely aggressive anti-bot targets may still block some requests; failures are reported honestly per URL
- Data quality mirrors the source: if a page hides its data behind images or canvas, extraction may be partial

## Troubleshooting

- **Empty dataset?** Check the run log - each URL is reported with `ok`, `skipped` or `error` and a reason; fix the flagged targets and re-run
- **Blocked or 403 responses?** The adaptive ladder escalates automatically; if a target still fails, lower `max_items` and retry later, or schedule runs further apart
- **Unexpected fields?** Compare your output against the example below - `data_path` (where present) controls which array is extracted
- **Run stopped early?** You hit the spending limit or `max_items` cap - raise the cap and resume; completed items are always flushed to the dataset

## FAQ

**What exactly does Pry ESG Scorecard Extractor deliver?** Extract ESG and sustainability metrics from corporate report pages and PDFs - emissions figures, diversity ratios, governance scores - each metric extracted into structured rows for compliance reporting. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**Which sites does this work on?** Any site embedding schema.org structured data (JSON-LD) - that includes Shopify, WooCommerce, Magento and most modern platforms. Pages without matching structured data are skipped and reported honestly rather than guessed at.

**What happens with pages that have no structured data?** They appear in the dataset with status 'skipped' and a clear reason - you always know exactly what was extracted versus what was not found.

**What does the **PDF extraction** option do?** Parse linked sustainability-report PDFs with OCR fallback. Default: `True`.

## Support

Issues and feature requests: [repository](https://codeberg.org/RugMunchMedia/pryscraper). Custom actors built on this engine are available on request.
