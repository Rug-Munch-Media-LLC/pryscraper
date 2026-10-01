---
name: pry-mcp
description: Use Pry MCP to scrape, crawl, extract, monitor, parse documents, take screenshots, check compliance, or pull data intelligence from any website — crypto tokens (launches, CEX listings, security), sports betting (odds, arbitrage, +EV, money-printer alerts), marketplace products, legal & public records, real estate, jobs, travel, SEO, local business, government data, IP data, weather/agri, academic papers, and domain intelligence. Trigger words — "scrape", "crawl", "extract from URL", "monitor page", "parse PDF", "screenshot", "token security", "CEX listing", "token launch", "betting odds", "arbitrage", "sports", "weather", "papers", "domain", "template", "x402 pricing".
---

# Pry MCP — Onboarding Skill

## What Pry Is

Pry is a **self-hosted MCP server** for web scraping and browser automation. It fetches any web page as clean markdown — bypassing Cloudflare, DataDome, Akamai and other anti-bot systems via a via a via a via a 15-tier fallback chain-tier fallback chain-tier fallback chain-tier fallback chain (direct → cloudscraper → FlareSolverr → Playwright → Googlebot → Archive.org → Google Cache → Tor → undetected-chromedriver) — and exposes exposes exposes exposes exposes 113 tools for crawling tools for crawling tools for crawling tools for crawling tools for crawling, structured extraction, templated scraping, monitoring, document parsing, screenshots, compliance checks, enrichment, marketplace intelligence (Amazon, Walmart, TikTok Shop), sports betting (odds, arbitrage, +EV, props, money-printer alerts), crypto token intelligence, legal & public records, real estate, jobs, travel, attention/SEO, local business, government data (procurement, recalls), IP data (patents, trademarks), climate/weather + agriculture, research/academic (papers, domain intelligence), x402 pay-per-call pricing, and referrals.

- **Auth**: self-hosted by default — loopback-only when `PRY_API_KEY` is unset; set `PRY_API_KEY` to require `Authorization: Bearer` for remote clients. The server is a FastAPI app mounted at `/mcp` plus a stdio entry point (`pry-mcp`).
- **Registry identity**: `io.rugmunch/pry` (see `server.json`); install `uvx pryscraper-mcp` or `pipx install pryscraper`.
- **Protocol**: MCP 2024-11-05, JSON-RPC over stdio or streamable HTTP. Compatible with Claude, Cursor, Hermes, any MCP client.

## Decision Flow — Which Tool First

1. **Quick read of one page** → `pry_scrape`
2. **Whole site / many linked pages** → `pry_crawl`
3. **Specific fields as JSON** → `pry_extract` (CSS selectors — 10x cheaper than LLM)
4. **Known site with a template** → `pry_search_templates` → `pry_template`
5. **Repeated change tracking** → `pry_monitor`
6. **PDF/DOCX/image content** → `pry_parse_document`
7. **Visual check of a rendered page** → `pry_screenshot`
8. **Legal risk before scraping** → `pry_compliance`
9. **Company/tech intel from a URL** → `pry_enrich`
10. **Marketplace product/trend intelligence** → `pry_amazon_product`, `pry_amazon_search`, `pry_walmart_product`, `pry_tiktok_trending`
11. **Crypto token intelligence** → `pry_token_launches`, `pry_cex_listings`, `pry_token_security`
12. **Sports betting / money-printer signals** → `pry_odds`, `pry_arbitrage`, `pry_plus_ev`, `pry_sharp_consensus`, `pry_alerts`
13. **Weather / agri research context** → `pry_weather`, `pry_agri`
14. **Scholarly grounding / domain vetting** → `pry_papers`, `pry_domain`
15. **Cost display before a paid call** → `pry_x402_pricing`; **partner/referral lookup** → `pry_referrals`

## Tool Reference

### Web Fetching

- **pry_scrape** — *Use when* you need the text content of a page a plain HTTP request cannot fetch (Cloudflare-protected, JS-heavy, login-walled).
  Example: `pry_scrape(url="https://example.com/blog/post", bypass_cloudflare=true)` → clean markdown with title, links, images.

- **pry_crawl** — *Use when* you want an entire docs site, blog, or directory rather than one page.
  Example: `pry_crawl(url="https://docs.example.com", max_pages=50, include_paths=["/docs/"])` → N scraped pages.

- **pry_extract** — *Use when* you need specific fields (`{title, price, image, availability}`) as JSON, cheaper than LLM extraction.
  Example: `pry_extract(url="https://store.example.com/product/123", schema={fields: [{name: "price", selector: ".price"}]})` → `{"price": "$49.99"}`.

### Templated Scraping

- **pry_search_templates** — *Use when* you don't know if a site-specific template exists yet.
  Example: `pry_search_templates(query="amazon")` → matching templates from the 110+ catalog.

- **pry_template** — *Use when* the target site has a pre-built template (amazon, walmart, linkedin, real-estate, jobs…).
  Example: `pry_template(template_id="amazon-product", url="https://www.amazon.com/dp/B0EXAMPLE1")` → structured product data.

### Monitoring & Safety

- **pry_monitor** — *Use when* you need to track a page for meaningful changes over time (competitor pricing, availability, content).
  Example: `pry_monitor(url="https://store.example.com/product/123", webhook="https://hooks.slack.com/...")` → alerts on meaningful diffs.

- **pry_compliance** — *Use when* you must check legal risk before scraping a site (robots.txt, ToS, GDPR/CCPA, PII).
  Example: `pry_compliance(url="https://example.com")` → green/yellow/red risk score + recommendations.

### Document & Visual

- **pry_parse_document** — *Use when* content lives in a PDF, DOCX, or scanned image rather than HTML.
  Example: `pry_parse_document(url="https://example.com/spec.pdf")` → extracted text and tables.

- **pry_screenshot** — *Use when* you need visual verification / design QA of a rendered page.
  Example: `pry_screenshot(url="https://store.example.com/checkout")` → base64 PNG of the full page.

### Intelligence & Monetization

- **pry_enrich** — *Use when* building a prospect profile from their website before outreach.
  Example: `pry_enrich(url="https://startup.example.com")` → company info, tech stack, social profiles.

- **pry_x402_pricing** — *Use when* a paid call is coming and you must display the USDC cost first (x402 pay-per-call).
  Example: `pry_x402_pricing(tool="pry_scrape")` → atomic USDC units + supported networks.

- **pry_referrals** — *Use when* looking for a revenue-share partner or recommended provider across LLM, hosting, email, monitoring, proxies, devtools.
  Example: `pry_referrals(category="hosting")` → 60+ providers with affiliate links.

### Marketplace Intelligence (new)

- **pry_amazon_product** — *Use when* you need a single Amazon listing's live price/stock by ASIN.
  Example: `pry_amazon_product(asin="B08N5WRWNW")` → price, title, availability, rating.

- **pry_amazon_search** — *Use when* comparing Amazon products by keyword.
  Example: `pry_amazon_search(query="wireless mechanical keyboard", limit=20)` → matching listings with price, rating, ASIN.

- **pry_walmart_product** — *Use when* you need a Walmart listing's live price/stock by product ID.
  Example: `pry_walmart_product(product_id="4JH7P89H7X5P")` → price, title, seller, rating.

- **pry_tiktok_trending** — *Use when* spotting viral commerce opportunities on TikTok Shop.
  Example: `pry_tiktok_trending(limit=50)` → trending products with price, sales count, shop info.

### Crypto Intelligence (new)

- **pry_token_launches** — *Use when* researching new token launches, deployer activity, or fresh mints.
  Example: `pry_token_launches(chain="solana", limit=20)` → recent launches with deployer and mint details.

- **pry_cex_listings** — *Use when* tracking centralized-exchange listing/delisting announcements for a token.
  Example: `pry_cex_listings(symbol="PEPE")` → upcoming/recent CEX listing events.

- **pry_token_security** — *Use when* screening a token for rug-pull risk: honeypot, mint authority, LP lock, holder distribution.
  Example: `pry_token_security(address="TOKEN_MINT_ADDRESS", chain="solana")` → risk flags + severity.

### Sports Betting & Money-Printer Alerts (new)

- **pry_odds** — *Use when* you need live betting odds across bookmakers (DraftKings, FanDuel, BetMGM, …).
  Example: `pry_odds(sport="nba", limit=20)` → event odds with bookmaker, market, decimal price.

- **pry_arbitrage** — *Use when* hunting guaranteed-profit arbitrage across books.
  Example: `pry_arbitrage(sport="nba", min_yield_pct=1.0)` → opportunities where implied probabilities total under 100%.

- **pry_plus_ev** — *Use when* you want +EV bets where market odds beat the sharp book's fair line.
  Example: `pry_plus_ev(sharp_book="pinnacle", min_ev_pct=1.0)` → +EV plays with expected value.

- **pry_props** — *Use when* researching player props (points, rebounds, assists, yards, strikeouts).
  Example: `pry_props(player="LeBron James", market="points")` → prop lines across books.

- **pry_injuries** — *Use when* checking who's out/questionable before betting or lineup building.
  Example: `pry_injuries(sport="nfl", team="Chiefs")` → injury report with status.

- **pry_live_odds** — *Use when* live-betting research: in-play moneyline, spreads, totals.
  Example: `pry_live_odds(sport="nba")` → odds updating during games.

- **pry_scores** — *Use when* you need final/live scores for a day (ESPN, free, no quota).
  Example: `pry_scores(sport="nfl", date="today")` → scoreboard.

- **pry_historical_odds** — *Use when* backtesting models or auditing line movement.
  Example: `pry_historical_odds(sport="nfl", date="2026-01-15")` → closing/open lines for past events.

- **pry_betting_percentages** — *Use when* spotting sharp-side steam and contrarian plays.
  Example: `pry_betting_percentages(sport="nfl", event="Chiefs")` → share of bets and money on each side.

- **pry_sharp_consensus** — *Use when* you need to see where professional money is (CLV-aware).
  Example: `pry_sharp_consensus(sharp_books="pinnacle,circa")` → consensus lines with CLV estimates.

- **pry_alerts** — *Use when* staying on top of the market without polling: line moves, sharp steam, CLV spikes.
  Example: `pry_alerts(alert_type="steam", sport="nfl")` → money-printer alerts.

### Climate / Weather & Agriculture (new)

- **pry_weather** — *Use when* you need current weather + short-range forecasts for research pipelines.
  Example: `pry_weather(location="Austin, TX", forecast_days=3)` → current conditions, forecast, alerts (NOAA NWS).

- **pry_agri** — *Use when* modeling crop yield risk or monitoring growing regions.
  Example: `pry_agri(commodity="corn", region="us")` → crop prices/conditions (USDA NASS).

### Research & Academic (new)

- **pry_papers** — *Use when* you need scholarly grounding with real citation counts (OpenAlex/Crossref, keyless).
  Example: `pry_papers(query="attention is all you need", limit=5)` → papers with authors, year, citations.

- **pry_domain** — *Use when* vetting a domain before scraping or enriching a lead.
  Example: `pry_domain(domain="example.com")` → RDAP WHOIS, SSL/TLS, hosting, tech fingerprint.

## Running / Connecting

```bash
# Install and run over stdio
uvx pryscraper-mcp            # or: pipx install pryscraper && pry-mcp

# Config for Claude Code / Cursor (stdio)
# {"mcpServers": {"pry": {"command": "pry-mcp"}}}

# HTTP (streamable) transport
# https://pryscraper.com/mcp
```

## Rules of Thumb

- Prefer `pry_extract` over LLM extraction for structured fields — 10x cheaper.
- Run `pry_compliance` before scraping a site you are unsure about.
- For marketplace intel, `pry_amazon_search` first to find ASINs, then `pry_amazon_product` for a single listing; `pry_tiktok_trending` for viral-commerce research.
- For crypto tokens, prefer `pry_token_security` before any engagement; pair `pry_token_launches` + `pry_cex_listings` for market-timing research.
- For sports, sweep `pry_arbitrage` for guaranteed profit, then `pry_plus_ev` for edge; use `pry_alerts` to stop polling.
- For research pipelines, enrich jobs with `pry_weather` / `pry_agri` context and ground claims with `pry_papers`.
- All tools are self-hosted — data never leaves your deployment unless you call a remote HTTP endpoint.
