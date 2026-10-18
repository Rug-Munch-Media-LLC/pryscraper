# Pry Sports Odds Comparison

Real-time sports odds comparison across 112+ sportsbooks. Find the best line on every bet, detect arbitrage opportunities, and identify +EV bets with closing line value analysis. Covers NFL, NBA, MLB, NHL, NCAA, soccer, tennis, golf, MMA, and more. Updates every minute with line movement tracking.

## Input

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process (ESPN / odds API endpoints to scrape). |
| `sport` | string | no | Sport filter: all, nfl, nba, mlb, nhl, ncaaf, ncaab, soccer, mma, tennis, or any supported league key. |
| `market_types` | array | no | Which markets to compare: h2h (moneyline), spreads, totals. |
| `include_arbitrage` | boolean | no | Detect arbitrage opportunities across books: legs, books, guaranteed ROI, stake split. |
| `include_ev` | boolean | no | Identify +EV opportunities: fair probability, best price, edge percentage, EV per unit. |
| `max_items` | integer | no | Hard cap on processed items for this run - keeps trial costs predictable. Billing stops when the cap or your spending limit is reached. |
| `proxy_configuration` | object | no | Apify proxy settings passed through to Pry's premium-proxy tier. Leave default to use the platform proxy automatically. |

## Output

One dataset item per processed URL. Fields:

`url`, `status`, `sport`, `event_id`, `event_name`, `commence_time`, `best_odds`, `arbitrage_opportunities`, `ev_opportunities`, `line_movements`, `method`, `error`, `scraped_at`, `metadata`, `content`, `data`

## Billing

Pay-per-event: one `odds-comparison-pulled` event per processed URL. Your spending limit is honoured; the run stops gracefully at the cap.

## Notes

- Requires no Pry-specific credentials; the upstream data endpoints must be reachable from the Apify runtime.
- Report sections that depend on unavailable upstream modules degrade to empty values rather than failing the run.
