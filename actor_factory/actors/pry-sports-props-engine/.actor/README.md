# Pry Sports Props Engine

Comprehensive player prop betting intelligence: live props across 112+ books, lineup data, player recent stats with hot/cold streaks, defensive matchup context, and prop line movement tracking. Covers NBA, NFL, MLB, NHL player points, rebounds, assists, yards, touchdowns, strikeouts, and more. The most detailed player props actor on Apify.

## Input

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | array | yes | One or more https:// URLs to process (ESPN / odds API endpoints to scrape). |
| `sport` | string | no | Sport slug: nba, nfl, mlb, nhl, or any supported league key. |
| `team` | string | no | Optional team filter (e.g. "Lakers", "Boston Celtics"). Used for lineup data and matchup context. |
| `player_name` | string | no | Optional player filter (e.g. "LeBron James"). Narrows live props and recent stats to one player. |
| `include_lineups` | boolean | no | Attach active/projected lineups, injury reports, and minutes projections. |
| `include_stats` | boolean | no | Attach last-N-games player stats with hot/cold streak trends. |
| `include_matchup_context` | boolean | no | Attach defensive-ranking matchup context for the prop slate. |
| `max_items` | integer | no | Hard cap on processed items for this run - keeps trial costs predictable. Billing stops when the cap or your spending limit is reached. |
| `proxy_configuration` | object | no | Apify proxy settings passed through to Pry's premium-proxy tier. Leave default to use the platform proxy automatically. |

## Output

One dataset item per processed URL. Fields:

`url`, `status`, `sport`, `team`, `player_name`, `props`, `lineup_data`, `recent_stats`, `streaks`, `defensive_context`, `method`, `error`, `scraped_at`, `metadata`, `content`, `data`

## Billing

Pay-per-event: one `props-pulled` event per processed URL. Your spending limit is honoured; the run stops gracefully at the cap.

## Notes

- Requires no Pry-specific credentials; the upstream data endpoints must be reachable from the Apify runtime.
- Report sections that depend on unavailable upstream modules degrade to empty values rather than failing the run.
