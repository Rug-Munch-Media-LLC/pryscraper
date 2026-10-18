# Pry Sports Betting Intelligence

Comprehensive sports betting intelligence: live odds across 112+ books, arbitrage detection, +EV opportunities, player props, live in-game analytics, sharp money tracking (steam moves, RLM, bet/money divergence), weather impact, lineup data, prediction market cross-reference, Kelly criterion stake sizing, and futures odds. The most complete sports betting data actor on Apify.

## Input

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process (ESPN / odds API endpoints to scrape). |
| `report_type` | string | no | Which intelligence report to generate: full (everything), odds_only, sharp_only, props_only, live_only, or weather_only. |
| `sport` | string | no | Sport filter: all, nfl, nba, mlb, nhl, ncaaf, ncaab, soccer, mma, tennis, or any supported league key. |
| `include_prediction_markets` | boolean | no | Cross-reference sportsbook odds against prediction market prices (Polymarket/Kalshi style venues). |
| `include_weather` | boolean | no | Attach weather conditions and betting-impact assessment for outdoor events. |
| `include_sharp_intel` | boolean | no | Track steam moves, reverse line movement (RLM), and bet/money percentage divergence. |
| `include_kelly` | boolean | no | Compute fractional Kelly stake sizing for detected +EV opportunities. |
| `max_items` | integer | no | Hard cap on processed items for this run - keeps trial costs predictable. Billing stops when the cap or your spending limit is reached. |
| `proxy_configuration` | object | no | Apify proxy settings passed through to Pry's premium-proxy tier. Leave default to use the platform proxy automatically. |

## Output

One dataset item per processed URL. Fields:

`url`, `status`, `report_type`, `sport`, `event_id`, `event_name`, `commence_time`, `odds`, `arbitrage`, `ev`, `props`, `live_state`, `weather`, `sharp_intel`, `prediction_markets`, `kelly_sizing`, `method`, `error`, `scraped_at`, `metadata`, `content`, `data`

## Billing

Pay-per-event: one `betting-intel-generated` event per processed URL. Your spending limit is honoured; the run stops gracefully at the cap.

## Notes

- Requires no Pry-specific credentials; the upstream data endpoints must be reachable from the Apify runtime.
- Report sections that depend on unavailable upstream modules degrade to empty values rather than failing the run.
