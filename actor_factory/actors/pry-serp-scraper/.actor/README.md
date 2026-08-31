# Pry SERP Scraper

Scrape Google search results pages: organic listings, ads, featured snippets and People Also Ask - via TLS-fingerprint and Googlebot-emulation tiers purpose-built for search engines. Structured JSON out, CAPTCHA escalation automatic.

> Looking to **serp data at scale**, need a reliable **serp scraper**, or want **scraper monitoring** without infrastructure headaches? This actor handles it on Apify's managed runtime.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **3 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Tutorial

1. Add your target URLs to the `urls` field (one per entry).
2. Adjust optional settings or keep the defaults - they're tuned for the common case.
3. Click **Start** - results stream into the dataset as each URL finishes.
4. Export as JSON/CSV/Excel, or consume via API/webhook.

## How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0030` per `serp-scraped` (one search results page parsed into structured listings.) - that is **$3.00 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 512 MB costs roughly **$0.30** in event charges (platform compute adds about $0.0333). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `serp-scraped` | SERP scraped | $0.0030 | One search results page parsed into structured listings. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `num_results` | integer | no | Number of organic results to parse per page. |
| `include_ads` | boolean | no | Also extract sponsored listings. |

## Output reference

Each dataset item looks like this:

```json
{
  "url": "https://example.com",
  "status": "ok",
  "method": "direct",
  "scraped_at": "2026-01-01T00:00:00+00:00",
  "content": "# Example page\n\nClean markdown content...",
  "metadata": {
    "domain": "example.com",
    "content_length": 1234
  }
}
```

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## How can I use this data?

- **Market research** - track serp scraped trends across competitors
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

**What exactly does Pry SERP Scraper deliver?** Scrape Google search results pages: organic listings, ads, featured snippets and People Also Ask - via TLS-fingerprint and Googlebot-emulation tiers purpose-built for search engines. Structured JSON out, CAPTCHA escalation automatic. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**What does the **Results per query** option do?** Number of organic results to parse per page. Default: `20`.

**What does the **Include ads** option do?** Also extract sponsored listings. Default: `False`.

## Support

Issues and feature requests: [repository](https://github.com/cryptorugmuncher/pryscraper). Custom actors built on this engine are available on request.
