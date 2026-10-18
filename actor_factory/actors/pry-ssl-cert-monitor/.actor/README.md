# Pry SSL Certificate Monitor

Probe TLS certificates per host: issuer, expiry date, days left and an expiring-soon flag from a live handshake.

> Need **ssl certificate monitor data** without infrastructure headaches? This actor scrapes, monitors and exports it on Apify's managed runtime - pay per result, no subscription.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## Scope and data sources

This actor does exactly one thing, and says so above. It does not claim capabilities beyond the items listed under Limitations; anything unavailable is returned with an explicit `unavailable` or `error` field rather than fabricated data.

## What it does

SSL Certificate Monitor delivers fresh ssl certificate monitor as clean, structured data you can actually use - no infrastructure to run, no proxies to manage, no parsers to maintain. Point it at your targets, and every result lands in the dataset with a per-URL status so downstream jobs can trust what they consume. You pay only for successfully processed items.

## What can this Actor do?

- Process **2 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Use Cases

- **Continuous monitoring** - schedule the actor to pull fresh ssl certificate monitor data on the cadence you need (hourly, daily, weekly) and alert via webhooks when anything changes
- **Market & competitive research** - bulk-collect ssl certificate monitor records into one dataset to benchmark competitors, prices and trends over time
- **AI & analytics pipelines** - export clean, structured cert checked results to JSON/CSV/Excel, or feed them straight into LLM/RAG workflows, BI dashboards or a warehouse via the Apify API
## Tutorial

1. Add your target URLs to the `urls` field (one per entry).
2. Adjust optional settings or keep the defaults - they're tuned for the common case.
3. Click **Start** - results stream into the dataset as each URL finishes.
4. Export as JSON/CSV/Excel, or consume via API/webhook.

## Pricing

### How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0030` per `cert-checked` (one domain's tls certificate probed.) - that is **$3.00 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 256 MB costs roughly **$0.30** in event charges (platform compute adds about $0.0167). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `cert-checked` | Certificate checked | $0.0030 | One domain's TLS certificate probed. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `warn_days` | integer | no | Emit a warning item when expiry is within this window. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://www.cloudflare.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "content": "# Example page\n\nClean markdown content...",
  "metadata": {
    "domain": "www.cloudflare.com",
    "content_length": 1234
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

- **Market research** - track cert checked trends across competitors
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
  -d '{"urls": ["https://www.cloudflare.com"]}'
```

Integrations: Zapier, Make, n8n, Airbyte and webhooks are first-class on the Apify platform.

## Limitations

- Performs one live TLS handshake per host on port 443 and reports issuer, expiry and `days_left`
- No certificate transparency logs, chain validation report, or historical issuer tracking
- Hosts that refuse TLS or time out return `status=error` with `tls_error` - never a fabricated certificate

## Troubleshooting

- **Empty dataset?** Check the run log - each URL is reported with `ok`, `skipped` or `error` and a reason; fix the flagged targets and re-run
- **Blocked or 403 responses?** The adaptive ladder escalates automatically; if a target still fails, lower `max_items` and retry later, or schedule runs further apart
- **Unexpected fields?** Compare your output against the example below - `data_path` (where present) controls which array is extracted
- **Run stopped early?** You hit the spending limit or `max_items` cap - raise the cap and resume; completed items are always flushed to the dataset

## Tips

- **Start small, then scale**: validate output on 2-3 URLs first, then raise `max_items` and schedule bulk runs - failed targets are reported per-URL, so retries are cheap
- **Automate the boring part**: pair an Apify schedule with a webhook and the dataset lands in your pipeline without any manual runs

## FAQ

**What exactly does Pry SSL Certificate Monitor deliver?** Watch TLS certificate health across your domains: expiry countdowns, issuer changes and handshake failures - caught by connection-level probes before browsers scare your visitors. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**What does the **Warn before expiry (days)** option do?** Emit a warning item when expiry is within this window. Default: `14`.

## Support

Issues and feature requests: [repository](https://codeberg.org/RugMunchMedia/pryscraper). Questions or custom-actor requests: [support@pryscraper.com](mailto:support@pryscraper.com).
