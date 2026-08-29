# MCP Server

Pry exposes 73 MCP tools across 27 categories. Every tool has structured input/output schemas and annotations.

## Connecting

### SSE (Server-Sent Events)

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/sse"
    }
  }
}
```

### Streamable HTTP

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

### stdio

```bash
pry mcp --stdio
```

## Tools (73 total, 27 categories)

### Web Scraping (6 tools)
- `pry_scrape` — Scrape any URL to markdown
- `pry_crawl` — Crawl entire websites
- `pry_screenshot` — Full-page screenshots
- `pry_template` — Execute 110+ pre-built templates
- `pry_search_templates` — Search template catalog
- `pry_scrape_methods` — Get available scraping methods

### Sports Betting (13 tools)
- `pry_odds` — Get odds from 112+ sportsbooks
- `pry_arbitrage` — Find arbitrage opportunities
- `pry_plus_ev` — Find +EV bets
- `pry_live_odds` — Live in-game odds
- `pry_props` — Player props
- `pry_injuries` — Injury reports
- `pry_scores` — Live scores
- `pry_historical_odds` — Historical odds data
- `pry_sharp_consensus` — Sharp money consensus
- `pry_books` — Bookmaker coverage
- `pry_book_coverage` — Book-specific coverage
- `pry_betting_percentages` — Public betting percentages
- `pry_all_sources` — All available sources

### Legal Intelligence (5 tools)
- `pry_legal_dockets` — Court dockets (CourtListener)
- `pry_legal_sec` — SEC EDGAR filings
- `pry_legal_sanctions` — OFAC sanctions list
- `pry_patents` — Patent search
- `pry_trademarks` — Trademark search

### Government (3 tools)
- `pry_contracts` — Government contracts (SAM.gov)
- `pry_grants` — Government grants
- `pry_procurement` — Procurement data

### Data Domains (20+ categories)
Jobs, real estate, news, energy, freight, food, grocery, deals, travel, events, research, patents, trademarks, sentiment, reviews, app store, weather, compliance, crypto, and more.

## Tool Annotations

Every tool declares:
- `readOnlyHint` — Does it modify state?
- `destructiveHint` — Does it delete data?
- `idempotentHint` — Is it safe to retry?

## Discovery

```
GET /mcp/health → Server info, tool count, transports
POST /mcp/ {"method": "tools/list"} → Full tool catalog
```
