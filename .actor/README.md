# Pry Universal Scraper

Scrape any website to clean markdown with a 12-tier adaptive anti-bot bypass (Cloudflare, DataDome, Akamai). Pay per page scraped; blocked pages escalate automatically.

Built on [Pry](https://github.com/cryptorugmuncher/pryscraper): 12-tier adaptive anti-bot bypass (Cloudflare, DataDome, Akamai), block-signal detection, and circuit breakers.

## Pricing (pay-per-event)

| Event | Title | Price | Description |
|---|---|---|---|
| `page-scraped` | Page scraped | $0.0040 | One URL scraped through the fallback chain. |

The platform also bills synthetic events automatically (`apify-actor-start`, `apify-default-dataset-item`).

## Input

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process. |
| `output_format` | string | no | Content format pushed to the dataset. |
| `timeout` | integer | no | Per-URL timeout. |

## Output

Dataset items: `url`, `status` (`ok`/`error`), `content`, `method`, `error`, `scraped_at`, `metadata`. Error items are pushed (and charged) for invalid targets too - work done is work billed, transparently.
