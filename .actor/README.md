# Pry Universal Scraper

Scrape any website to clean markdown with a 12-tier adaptive anti-bot bypass (Cloudflare, DataDome, Akamai). Pay per page scraped; blocked pages escalate automatically.

> Looking to **universal data at scale**, need a reliable **universal scraper**, or want **scraper monitoring** without infrastructure headaches? This actor handles it on Apify's managed runtime.

**Pry Universal Scraper** runs on the [Pry](https://github.com/cryptorugmuncher/pryscraper) engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **3 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Tutorial

1. Add your target URLs to the `urls` field (one per entry).
2. Adjust optional settings (output format, timeouts) or keep defaults.
3. Click **Start** - results stream into the dataset as each URL finishes.
4. Export the dataset as JSON/CSV/Excel, or consume it via API/webhook.

## How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0040` per `page-scraped` (one url scraped through the fallback chain.) - that is **$4.00 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 512 MB costs roughly **$0.40** in event charges (platform compute adds about $0.0333). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `page-scraped` | Page scraped | $0.0040 | One URL scraped through the fallback chain. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `output_format` | string | no | Content format pushed to the dataset. |
| `timeout` | integer | no | Per-URL timeout. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://example.com",
  "status": "ok",
  "content": "# Example page\n\nClean markdown content...",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "metadata": {
    "domain": "example.com",
    "content_length": 1234
  }
}
```

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## How can I use this data?

- **Market research** - track page scraped trends across competitors
- **Alerting** - pair with Apify schedules + webhooks for real-time notifications
- **AI pipelines** - dataset exports feed directly into LLM/RAG workflows
- **Reporting** - export to JSON/CSV/Excel or consume via the Apify API in your own tools

## More Pry actors

This actor is part of the [Pry actor family](https://apify.com/cryptorugmuncher) - 50+ scrapers, crawlers and monitors covering SERP, maps leads, LLM corpora, compliance monitoring and dark-web sources. Same engine, same reliability, one subscription-free billing model.

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

**Is scraping legal?** Scraping publicly available data is generally legal; respect robots.txt, ToS and privacy law. Pry ships compliance tooling (consent, deletion, retention) in the self-hosted core.

**What about sites behind Cloudflare?** That is exactly what the adaptive ladder solves - blocked responses trigger automatic escalation to stealth browser tiers.

**Can I schedule runs?** Yes - scheduling, monitoring and API access are first-class Apify platform features. Monitors pair especially well with hourly or daily schedules.

## Support

Issues and feature requests: [Pry repository](https://github.com/cryptorugmuncher/pryscraper). Custom actors built on this engine are available on request.
