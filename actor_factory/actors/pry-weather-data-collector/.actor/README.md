# Pry Weather Data Collector

Collect weather observations and forecasts from any forecast page - temperature, precipitation and condition signals normalized into flat rows for analytics and alerting pipelines.

> Looking to **weather data at scale**, need a reliable **weather scraper**, or want **weather monitoring** without infrastructure headaches? This actor handles it on Apify's managed runtime.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **3 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Tutorial

1. Add the page(s) or feed(s) to watch in `urls`.
2. Run once - that first run captures the **baseline** fingerprint.
3. Schedule runs (hourly/daily both work). Changed pages land in the dataset with a similarity detail; unchanged ones stay quiet.
4. Want an audit trail instead? Flip on `include_unchanged` and every capture is kept.

## How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0010` per `observation-collected` (one weather observation collected.) - that is **$1.00 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 256 MB costs roughly **$0.10** in event charges (platform compute adds about $0.0167). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `observation-collected` | Observation collected | $0.0010 | One weather observation collected. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `change_threshold` | integer | no | SimHash bit distance above this counts as changed (0 = any difference, 3 default, 10+ only major rewrites). |
| `urls` | array | yes | One or more https:// URLs to process. |
| `location_label` | string | no | Tag every row with this location identifier. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://example.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "monitor": {
    "fingerprint": "1100011010110100",
    "changed": true,
    "detail": "simhash distance 9 (threshold 3)"
  }
}
```

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## How can I use this data?

- **Market research** - track observation collected trends across competitors
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

**What exactly does Pry Weather Data Collector deliver?** Collect weather observations and forecasts from any forecast page - temperature, precipitation and condition signals normalized into flat rows for analytics and alerting pipelines. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**How should I schedule this?** Hourly or daily schedules are the sweet spot. First run captures a baseline; after that you only hear about actual changes. Apify scheduling handles the rest.

**How does change detection work?** Each capture computes a stable content fingerprint; the next run compares against it and reports changed/unchanged with a similarity detail. The first run is always a baseline.

**Will I get an item every run even when nothing changed?** By default unchanged pages are suppressed so your dataset only holds signal. Set include_unchanged to keep every capture for audit trails.

**What does the **Change threshold** option do?** SimHash bit distance above this counts as changed (0 = any difference, 3 default, 10+ only major rewrites). Default: `3`.

**What does the **Location label** option do?** Tag every row with this location identifier.

## Support

Issues and feature requests: [repository](https://github.com/cryptorugmuncher/pryscraper). Custom actors built on this engine are available on request.
