# Pry — Feature & Tool Catalog

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Feature & Tool Catalog
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-08-30
audience:
  - engineers
  - agents
  - integrators
note: Every count below is traced to source. The live source of truth is `pry_mcp/tools.py` (PRY_TOOLS) and `src/pry/api/registry_metadata.py` (get_tools_by_category / get_registry_manifest).
---

# Tool Catalog

Pry exposes **99 MCP tools** across **33 categories**. Each tool has a
structured input/output schema, annotation hints (`readOnlyHint`,
`destructiveHint`, `idempotentHint`), a registry category, and (where gated)
an x402 operation with server-authoritative pricing.

> **Count source of truth**
> - `pry_mcp/tools/` — `PRY_TOOLS`, 99 `"name"` entries (verify with
>   `grep -cE '"name": "'`).
> - `src/pry/api/registry_metadata.py` — `get_tools_by_category()` returns
>   33 category groups; `get_registry_manifest()` reports `tools.count = 99`.
> - `server.json`, `glama.json`, `registry_manifest.json` each carry the same
>   99-tool payload (machine-readable registry listings).

---

## Scraping / Data-Acquisition Categories

### web_scraping (6)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_scrape` | `scrape` | $0.001 | Scrape any URL to clean markdown; 15-tier anti-bot fallback |
| `pry_crawl` | `crawl` | $0.01 | Crawl up to 10 pages from a start URL |
| `pry_template` | `template_execute` | $0.002 | Execute a pre-built scraper template |
| `pry_search_templates` | free (listing) | $0 | List the 110+ available scraper templates |
| `pry_screenshot` | free per README (route `/v1/screenshot`) | $0 | Capture a full-page screenshot |
| `pry_scrape_methods` | `scrape_methods` | $0.002 | Query the per-domain scraping-method registry |

### data_extraction (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_extract` | `extract` | $0.005 | Structured extraction via CSS selectors or LLM |

### document_processing (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_parse_document` | `pdf_extract` | $0.01 | Parse documents (PDF/DOCX/CSV/JSON) into structured data |

### data_enrichment (2)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_enrich` | `extract` (+LLM) | $0.005+ | Enrich content — tech-stack, metadata, entities |
| `pry_domain` | `domain` | $0.002 | Domain intelligence report (WHOIS/SSL/hosting/tech) |

### monitoring (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_monitor` | `monitor` | $0.02 | Create a scheduled content monitor |

### compliance (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_compliance` | `compliance_search` | $0.003 | Regulatory / compliance records search |

---

## KOL / Leaderboard & Beta Spider (crypto)

### crypto (4)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_kol_leaderboards` | — | $0 | KOL / influencer leaderboard spider |
| `pry_token_launches` | `token_launches` | $0.002 | Crypto token launches / pairs / trending |
| `pry_cex_listings` | `cex_listings` | $0.002 | CEX listing & delisting signals |
| `pry_token_security` | `token_security` | $0.005 | Token security scan (honeypot / rugpull checks) |

---

## Data-Domain Categories

### legal (5)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_legal_dockets` | `legal_dockets` | $0.005 | U.S. court docket search (CourtListener) |
| `pry_legal_sec` | `legal_sec` | $0.005 | SEC EDGAR filings / insider trades |
| `pry_legal_sanctions` | `legal_sanctions` | $0.002 | OFAC SDN sanctions name screening |
| `pry_patents` | `patents` | $0.005 | USPTO patent search |
| `pry_trademarks` | `trademarks` | $0.005 | USPTO trademark search |

### government (3)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_procurement` | `procurement` | $0.005 | U.S. federal procurement opportunities (SAM.gov) |
| `pry_contracts` | `bidding_contracts` | $0.005 | Government contract bidding data |
| `pry_grants` | `bidding_contracts` | $0.005 | Government grant bidding data |

### jobs_careers (2)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_jobs_list` | `jobs_list` | $0.002 | ATS job listings (Greenhouse/Lever/Ashby/Workday) |
| `pry_jobs_salary` | `jobs_salary` | $0.002 | Salary bands (Levels.fyi) |

### travel (2)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_flights_grid` | `flights_grid` | $0.01 | Cheapest-flight-per-day grid (Google Flights) |
| `pry_hotel_rates` | `hotel_rates` | $0.01 | Per-night hotel rates (Google Hotels/Booking) |

### real_estate (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_realestate_search` | `realestate_search` | $0.005 | Real-estate listing search (Zillow/Redfin) |

### local (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_places_search` | `places_search` | $0.003 | Google Maps local business search |

### retail (4)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_deals` | `deals_search` | $0.002 | Deals / discounts / promotions search |
| `pry_resale` | `deals_search` | $0.002 | Resale / secondhand listings |
| `pry_grocery` | `food_grocery` | $0.002 | Grocery prices by item / ZIP |
| `pry_restaurant` | `food_grocery` | $0.002 | Restaurant menu pricing |

### utility (4)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_amazon_product` | — | $0.002 | Amazon product detail (via marketplace) |
| `pry_amazon_search` | — | $0.002 | Amazon product search |
| `pry_walmart_product` | — | $0.002 | Walmart product detail |
| `pry_tiktok_trending` | — | $0.002 | TikTok trending / app-capability data |

---

## Sports Betting (13 tools — flat $0.01/scan)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_odds` | `sports_odds` | $0.01 | Live sports betting odds |
| `pry_arbitrage` | `sports_arbitrage` | $0.01 | Arbitrage opportunities |
| `pry_plus_ev` | `sports_plus_ev` | $0.01 | Positive-EV betting opportunities |
| `pry_props` | `sports_props` | $0.01 | Player prop betting lines |
| `pry_injuries` | `sports_injuries` | $0.01 | Sports injury report |
| `pry_live_odds` | `sports_live` | $0.01 | Live in-play odds |
| `pry_scores` | `sports_scores` | $0.01 | Sports scores for a day |
| `pry_historical_odds` | `sports_historical` | $0.01 | Historical betting odds |
| `pry_betting_percentages` | `sports_betting_percentages` | $0.01 | Public betting percentages |
| `pry_sharp_consensus` | `sports_sharp_consensus` | $0.01 | Sharp consensus lines |
| `pry_books` | `sports_books` | $0.01 | 112-book aggregated odds / coverage |
| `pry_book_coverage` | `sports_books` | $0.01 | Sportsbook coverage-registry stats |
| `pry_all_sources` | `sports_books` | $0.01 | Aggregated odds across all sources |

---





## Prediction Markets (2 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_prediction_markets` | `prediction_markets` | $0.01 | Prediction market listings / odds |
| `pry_prediction_market_detail` | `prediction_market_detail` | $0.01 | Detail view for a single prediction market |

---

## Sports Futures (1 tool)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_futures` | `sports_futures` | $0.01 | Championship / season futures odds |

---

## Sports Derivatives (1 tool)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_derivatives` | `sports_derivatives` | $0.01 | Derivative / alternate betting lines |

---

## Sports Bankroll (1 tool)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_kelly_criterion` | `kelly_criterion` | $0.01 | Kelly-criterion stake sizing calculator |

---

## Player Intelligence (4 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_lineups` | `sports_lineups` | $0.01 | Projected / confirmed lineups |
| `pry_player_props_live` | `sports_props` | $0.01 | Live player prop lines |
| `pry_player_stats` | `sports_player_stats` | $0.01 | Player statistics lookup |
| `pry_props_matchup` | `sports_props` | $0.01 | Player prop matchup analysis |

---

## Sharp Money (5 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_steam_moves` | `sports_steam` | $0.01 | Steam move detection across books |
| `pry_reverse_line_movement` | `sports_reverse_line` | $0.01 | Reverse line movement signals |
| `pry_bet_money_divergence` | `sports_money_divergence` | $0.01 | Betting % vs money divergence |
| `pry_line_watch` | `sports_line_watch` | $0.01 | Watch line movement for a game |
| `pry_sharp_report` | `sports_sharp_report` | $0.01 | Sharp money report for a game |

---

## Live Analytics (5 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_live_games` | `sports_live` | $0.01 | Live games in progress |
| `pry_live_game_state` | `sports_live` | $0.01 | Detailed live game state |
| `pry_live_win_probability` | `sports_live` | $0.01 | Live win probability |
| `pry_live_scoring` | `sports_live` | $0.01 | Live scoring feed |
| `pry_live_betting_impact` | `sports_live` | $0.01 | Live events' betting impact |

---

## Game Context (3 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_game_weather` | `sports_weather` | $0.01 | Game-day weather conditions |
| `pry_weather_impact` | `sports_weather` | $0.01 | Weather impact on betting totals |
| `pry_game_context` | `sports_game_context` | $0.01 | Full game context bundle (weather, injuries, rest) |

---

## Social, Search, News & Sentiment

### social (3)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_sentiment` | `news_sentiment` | $0.002 | News / social sentiment analysis |
| `pry_reviews` | `reviews` | $0.003 | Google Maps / Yelp review history |
| `pry_app_reviews` | `app_store_reviews` | $0.002 | App Store user reviews by app id |

### search (3)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_serp` | `serp` | $0.003 | Google SERP scrape (organic + AI Overview + PAA) |
| `pry_trends` | `trends` | $0.003 | Google Trends interest timeline |
| `pry_mega_search` | `mega_search` | $0.003 | Consensus web search — six engines queried in parallel, hits ranked by cross-engine agreement |

### news_intelligence (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_news` | `news_search` | $0.002 | News article search by keyword |

### alerts (2)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_alerts` | `sports_alerts` | $0.01 | Money-printer alerts |
| `pry_drop_alert` | `drop_alert` | $0.002 | Product drop / restock alert check |

### business (2)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_firmographics` | — | $0.002 | Company firmographics / business data |
| `pry_company_watch` | `company_watch` | $0.005 | Company regulatory watch — enforcement & fines |

---

## Trade, Logistics, Energy, Events, Research, Safety, App Store

### trade (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_imports` | `supply_imports` | $0.004 | U.S. customs import records by company |

### logistics (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_freight` | `freight_rates` | $0.005 | Ocean container / FMC freight rates by route |

### energy (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_energy_lmp` | `energy_lmp` | $0.002 | Electricity locational marginal prices (LMP) by ISO |

### events (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_events` | `events_search` | $0.003 | Live event search (Ticketmaster/SeatGeek class) |

### data (weather) (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_weather` | `weather` | $0.002 | Current weather + short-range forecast |

### agriculture (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_agri` | `agri` | $0.002 | Agricultural climate indices / crop conditions |

### research (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_papers` | `academic` | $0.002 | Academic paper / preprint search |

### safety (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_recalls` | `recalls` | $0.005 | CPSC product recalls |

### app_store (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_app_search` | `app_store_search` | $0.002 | App Store app search by keyword |

---

## Payments / Billing / Account (3 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_x402_pricing` | free (manifest) | $0 | Quote the x402 price for an operation |
| `pry_balance` | free (control plane) | $0 | Read the prepaid USD balance for a user |
| `pry_buy_pack` | free (purchase; arms server-side gate) | $0 | Buy a bulk scrape-credit pack (USDC via x402) |

### affiliate / referrals (1)
| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_referrals` | free (catalog) | $0 | Referral program catalog |

---

## Actors / Marketplace (2 tools)

| Tool | Operation | Price | Purpose |
|------|-----------|:-----:|---------|
| `pry_actor_catalog` | free (listing) | $0 | List Apify Actor factory catalog |
| `pry_actor_run` | `browser_automation` | $0.05 | Run a factory Actor (browser automation) |

---

## Category Coverage Summary

| Category | Count | Category | Count |
|----------|:-----:|----------|:-----:|
| actors | 2 | local | 1 |
| affiliate | 1 | logistics | 1 |
| agriculture | 1 | monitoring | 1 |
| alerts | 2 | news_intelligence | 1 |
| app_store | 1 | payments | 1 |
| business | 2 | real_estate | 1 |
| compliance | 1 | research | 1 |
| crypto | 3 | retail | 4 |
| data | 3 | safety | 1 |
| data_enrichment | 2 | search | 2 |
| data_extraction | 1 | social | 3 |
| document_processing | 1 | sports_betting | 17 |
| energy | 1 | trade | 1 |
| events | 1 | travel | 2 |
| government | 3 | utility | 24 |
| jobs_careers | 2 | web_scraping | 6 |
| legal | 5 |  |  |

> Registry truth: `get_tools_by_category()` in `src/pry/api/registry_metadata.py` returns these
> 33 categories and 99 tools. The sports sections above are documentation groupings; the
> registry rolls several of them into `sports_betting` (17).

**Totals: 99 tools across 33 categories.**

> **Pricing note.** Price cells marked `$0` indicate the operation is
> explicitly classified free in `x402_middleware/classification.py`
> (`DEFAULT_FREE_PATHS`) or is a control-plane / discovery surface. Tools with
> `—` under Operation are surfaced by domain dispatchers whose operation is
> resolved per-request; the listed price is the domain default. Prices are
> **server-authoritative** — the middleware never trusts a client-supplied
> amount (see `docs/ops/PAYMENTS.md`).
