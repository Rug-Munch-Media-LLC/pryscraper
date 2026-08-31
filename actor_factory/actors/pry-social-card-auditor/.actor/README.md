# Pry Social Card Auditor

Audit Open Graph and social preview tags across every page of a site: missing og:title/og:image, thin descriptions and canonical conflicts - fix link previews before your next campaign.

> Need **social card auditor data** without infrastructure headaches? This actor scrapes, monitors and exports it on Apify's managed runtime - pay per result, no subscription.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What it does

Social Card Auditor delivers fresh social card auditor as clean, structured data you can actually use - no infrastructure to run, no proxies to manage, no parsers to maintain. Point it at your targets, and every result lands in the dataset with a per-URL status so downstream jobs can trust what they consume. You pay only for successfully processed items.

## What can this Actor do?

- Process **3 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Use Cases

- **Continuous monitoring** - schedule the actor to pull fresh social card auditor data on the cadence you need (hourly, daily, weekly) and alert via webhooks when anything changes
- **Market & competitive research** - bulk-collect social card auditor records into one dataset to benchmark competitors, prices and trends over time
- **AI & analytics pipelines** - export clean, structured page audited results to JSON/CSV/Excel, or feed them straight into LLM/RAG workflows, BI dashboards or a warehouse via the Apify API
## Tutorial

1. Drop your target URLs into `urls`.
2. Toggle only the checks you care about - each disabled check is compute you don't pay for.
3. Click **Start** - findings arrive severity-ranked with a 0-100 score per page.
4. Sort by score in the dataset view; worst offenders float up.

## Pricing

### How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0015` per `page-audited` (one page audited for social preview tags.) - that is **$1.50 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 256 MB costs roughly **$0.15** in event charges (platform compute adds about $0.0167). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `page-audited` | Page audited | $0.0015 | One page audited for social preview tags. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `max_pages` | integer | no | Hard cap on processed pages (runaway protection). |
| `require_og_image` | boolean | no | Flag pages missing a social preview image. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://www.theverge.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "audit": {
    "score": 75,
    "failed": 1,
    "warnings": 0,
    "findings": [
      {
        "check": "images_alt_text",
        "status": "warn",
        "detail": "2/6 images missing alt text"
      },
      {
        "check": "privacy_policy_link",
        "status": "fail",
        "detail": "no /privacy link on page"
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

- **Market research** - track page audited trends across competitors
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
  -d '{"urls": ["https://www.theverge.com"]}'
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

## Tips

- **Start small, then scale**: validate output on 2-3 URLs first, then raise `max_items` and schedule bulk runs - failed targets are reported per-URL, so retries are cheap
- **Automate the boring part**: pair an Apify schedule with a webhook and the dataset lands in your pipeline without any manual runs

## FAQ

**What exactly does Pry Social Card Auditor deliver?** Audit Open Graph and social preview tags across every page of a site: missing og:title/og:image, thin descriptions and canonical conflicts - fix link previews before your next campaign. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**What does the audit score mean?** A 0-100 weighted summary: each failed check costs 25 points, each warning 10. Individual findings always ship alongside the score so nothing is hidden behind a number.

**Can I disable checks I don't need?** Yes - every check is toggleable via the input options, so you pay only for the signals you care about.

**What does the **Max pages** option do?** Hard cap on processed pages (runaway protection). Default: `100`.

**What does the **Require og:image** option do?** Flag pages missing a social preview image. Default: `True`.

## Support

Issues and feature requests: [repository](https://codeberg.org/RugMunchMedia/pryscraper). Questions or custom-actor requests: [support@pryscraper.com](mailto:support@pryscraper.com).
