# Pry Knowledge Base Miner

Turn help centers and FAQ pages into clean question-answer pairs using FAQPage and HowTo structured data - training data for support chatbots, AI agents and self-service knowledge bases.

> Looking to **knowledge data at scale**, need a reliable **knowledge scraper**, or want **knowledge monitoring** without infrastructure headaches? This actor handles it on Apify's managed runtime.

This actor runs on the engine: a **12-tier adaptive anti-bot ladder** (Cloudflare, DataDome, Akamai) with per-domain memory, block-signal detection and circuit breakers. Cheaper tiers are tried first; escalation happens only when a target actually fights back.

## What can this Actor do?

- Process **3 configured input groups** - URLs in, structured results out
- **Adaptive bypass**: TLS fingerprinting, FlareSolverr, Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, archives
- **Transparent billing**: pay-per-event, charged per processed item
- **Platform perks**: scheduling, API access, proxy rotation, monitoring and webhooks come free with Apify

## Tutorial

1. Point `urls` at the pages carrying the structured data (product pages, recipe posts, FAQ centers...).
2. Keep defaults or narrow the entity types to extract.
3. Click **Start** - entities stream in as typed, flattened records; pages without matching data report as skipped.
4. Export via dataset UI, API, or webhook.

## How much will it cost to scrape with this Actor?

Billing is **pay-per-event**: you are charged `$0.0015` per `faq-pair-extracted` (one question-answer pair extracted to the dataset.) - that is **$1.50 per 1,000 items**, with no subscription and no minimum.

Example: 100 items at 512 MB costs roughly **$0.15** in event charges (platform compute adds about $0.0333). The synthetic `apify-actor-start` event covers startup compute. Your spending limit is always respected - the run stops gracefully at the cap.

### Events

| Event | Title | Price | Description |
|---|---|---|---|
| `faq-pair-extracted` | FAQ pair extracted | $0.0015 | One question-answer pair extracted to the dataset. |

## Input reference

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `max_pages` | integer | no | Hard cap on processed pages (runaway protection). |
| `min_answer_chars` | integer | no | Skip answers shorter than this many characters. |

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
        "type": "FAQPage",
        "fields": {
          "mainEntity[0].name": "How do I reset my password?",
          "mainEntity[0].acceptedAnswer.text": "Open Settings and choose Reset..."
        }
      }
    ]
  }
}
```

Items with `status: "error"` include an `error` reason - invalid targets are billed transparently and never silently dropped.

## How can I use this data?

- **Market research** - track faq pair extracted trends across competitors
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

**What exactly does Pry Knowledge Base Miner deliver?** Turn help centers and FAQ pages into clean question-answer pairs using FAQPage and HowTo structured data - training data for support chatbots, AI agents and self-service knowledge bases. Results land in the dataset as structured items with transparent status reporting.

**Is this allowed?** We stick to publicly available data and documented sources, and we respect robots.txt, ToS and privacy law. The core even ships compliance tooling - consent handling, deletion, retention - for self-hosters.

**What happens when a site blocks the request?** That's what the adaptive ladder is for. Blocked responses escalate automatically - headers first, stealth browsers later - until something gets through or every tier reports failure honestly.

**Can I run this on a schedule?** Absolutely - scheduling, API access and webhooks are first-class Apify features. Set it once and the dataset keeps itself fresh.

**Which sites does this work on?** Any site embedding schema.org structured data (JSON-LD) - that includes Shopify, WooCommerce, Magento and most modern platforms. Pages without matching structured data are skipped and reported honestly rather than guessed at.

**What happens with pages that have no structured data?** They appear in the dataset with status 'skipped' and a clear reason - you always know exactly what was extracted versus what was not found.

**What does the **Max pages** option do?** Hard cap on processed pages (runaway protection). Default: `100`.

**What does the **Minimum answer length** option do?** Skip answers shorter than this many characters. Default: `80`.

## Support

Issues and feature requests: [repository](https://codeberg.org/RugMunchMedia/pryscraper). Custom actors built on this engine are available on request.
