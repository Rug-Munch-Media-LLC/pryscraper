# MCP Tools

Pry exposes **76 MCP tools across 33 categories**. Every tool has a
structured input/output schema and MCP 2025-11-25 annotations.

Full machine-readable catalog: [`llms.txt`](https://codeberg.org/RugMunchMedia/pryscraper/raw/branch/main/llms.txt)
or `POST /mcp {"method": "tools/list"}`.

## Highlights by category

### Web scraping (6)
- `pry_scrape` — any URL → clean markdown, 15-tier anti-bot fallback ($0.001)
- `pry_crawl` — crawl up to 10 linked pages ($0.01)
- `pry_extract` — CSS-selector structured extraction, 10x cheaper than LLM ($0.005)
- `pry_template` / `pry_search_templates` — 110 pre-built templates ($0.002 / free)
- `pry_screenshot` — full-page screenshots
- `pry_scrape_methods` — per-domain scraping-method registry

### Monitoring & documents
- `pry_monitor` — scheduled content-change monitoring ($0.02)
- `pry_parse_document` — PDF/DOCX/CSV/JSON → structured data ($0.01)

### Sports betting (13)
`pry_odds`, `pry_arbitrage`, `pry_plus_ev`, `pry_live_odds`, `pry_props`,
`pry_injuries`, `pry_scores`, `pry_historical_odds`, `pry_sharp_consensus`,
`pry_books`, `pry_book_coverage`, `pry_betting_percentages`, `pry_all_sources`
— 112+ sportsbooks, flat $0.01/scan.

### Crypto (4)
`pry_token_launches`, `pry_cex_listings`, `pry_token_security`,
`pry_kol_leaderboards` — launches, CEX listing signals, honeypot/rugpull
scans, influencer leaderboards.

### Legal & government (8)
`pry_legal_dockets` (CourtListener), `pry_legal_sec` (SEC EDGAR),
`pry_legal_sanctions` (OFAC SDN), `pry_patents`, `pry_trademarks`,
`pry_procurement` (SAM.gov), `pry_contracts`, `pry_grants`.

### Data domains (20+ more)
Jobs, real estate, news, energy (LMP), freight, grocery, deals, travel
(flights/hotels), events, research papers, sentiment, reviews, app store,
weather/agri, compliance, domain intelligence, enrichment, local business,
and more.

## Tool annotations

Every tool declares:
- `readOnlyHint` — does it modify state?
- `destructiveHint` — does it delete data?
- `idempotentHint` — is it safe to retry?
- `openWorldHint` — does it reach the open web?

## Pricing

Paid tools return x402 402 challenges with server-authoritative prices;
listing/control-plane tools are free. See [x402 pricing](../x402/pricing).
