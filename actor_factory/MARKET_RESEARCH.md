# Apify Store Market Research — pry- Actor Opportunity Analysis

> Generated 2026-08-31. Source: apify.com/store scrape + docs.apify.com/actors/publishing.
> Cross-referenced against the 94 existing presets in `actor_factory/presets.py`.
> Purpose: input for the next agent building new presets. No code changes made.

---

## 1. Apify Store Landscape (scraped 2026-08-31)

Store size: **65,826 actors**. Headline stat: $1.5M paid out to developers last month; many earn $3k+/mo.

### Top categories (nav order = editorial priority)
1. Social media scrapers
2. AI (RAG/content crawlers)
3. Agents (MCP connectors)
4. Lead generation
5. E-commerce scrapers
6. SEO tools

### Most popular actors (by run count)
| Actor | Runs | Rating | Notes |
|---|---|---|---|
| compass/crawler-google-places | 583K | 4.7 | Google Maps, reviews+emails |
| apify/instagram-scraper | 380K | 4.7 | Full IG suite |
| clockworks/tiktok-scraper | 247K | 4.8 | TikTok suite |
| apify/instagram-profile-scraper | 207K | 4.8 | |
| apify/google-search-scraper | 173K | 4.6 | SERP API |
| apify/website-content-crawler | 151K | 4.6 | LLM/RAG corpus |
| curious_coder/linkedin-jobs-scraper | 144K | 4.6 | |
| streamers/youtube-scraper | 108K | 4.8 | |
| apidojo/tweet-scraper | 76K | 3.9 | $0.40/1K tweets |
| harvestapi/linkedin-profile-scraper | 66K | 4.6 | No-cookies LinkedIn |

### Pricing patterns observed
- **Pay-per-result (PPR)** dominates commodity scrapers: $0.18–$2.00 per 1K results (tweets $0.18–0.40/1K, FB ads $0.75/1K, Reddit $2/1K).
- **Pay-per-event (PPE)** used by higher-value/structured actors: events like `page-scraped`, `item-extracted`, `screenshot-taken` — typically $0.001–$0.05/event depending on complexity (simple page fetch at the low end; enriched/OCR/enrichment events at $0.01–0.05).
- **Monthly rental** ($20–$50/mo) for niche B2B tools; **free tier + paid limits** as a funnel (e.g., Douyin scraper "free tier — 10 runs").
- Rising-star actors (Douyin, Taobao, Northdata, Google Ads Transparency) all use per-result or per-event pricing — new entrants avoid flat rental.

### Publishing requirements (docs.apify.com/actors/publishing)
- Stages: development → publication + monetization setup → automated testing → promotion.
- Public actors require ongoing maintenance (~2h/week recommended), clear non-jargon README, periodic/automated testing, and no breaking changes without coordination (community@apify.com).
- Quality score + rating monitoring affect store visibility. Monetization models: PPR, PPE, rental (see /actors/publishing/monetize).

### Saturated vs underserved
**Saturated (avoid head-on):** Instagram/TikTok/Twitter/LinkedIn/Reddit/YouTube scrapers, Google Maps/Places, Google SERP, generic website-content crawlers, generic e-commerce price scrapers, lead-gen email finders.

**Underserved signals:** Rising-stars and "hidden gems" collections show demand for niche verticals (Douyin, Taobao, HRS reviews, Northdata EU registry, Google Ads Transparency). Regulatory/monitoring/vertical-data actors are sparse relative to search demand. WAF-protected targets (Cloudflare Enterprise, Akamai, DataDome) are where generic actors fail — our 15-tier anti-bot engine is the differentiator.

---

## 2. Overlap Analysis: Our 94 Presets vs the Store

### Competitive overlap (we'd fight incumbents — deprioritize as store SKUs)
| Our preset | Store incumbent | Verdict |
|---|---|---|
| pry-serp-scraper / pry-serp-rank-tracker | apify/google-search-scraper (173K runs) | Saturated |
| pry-product-data-extractor / pry-ecommerce-catalog-crawler / pry-price-watcher | apify/e-commerce-scraping-tool + dozens | Saturated |
| pry-lead-harvester / pry-maps-lead-extractor / pry-local-directory-extractor | compass/crawler-google-places (583K) | Saturated |
| pry-blog-post-extractor / pry-llm-corpus-builder / pry-site-crawler | apify/website-content-crawler (151K) | Saturated |
| pry-review-aggregator | Many per-platform review scrapers | Crowded |
| pry-jobs-aggregator | LinkedIn jobs scrapers (144K) | Crowded (but ours is multi-board) |
| pry-change-monitor / pry-sitemap-diff / pry-wayback-diff | apify Website Checker-type tools | Moderate competition |
| pry-news-feed-monitor / pry-rss-feed-monitor | Many RSS actors | Crowded |

### Our edge (unique or clearly differentiated vs store)
- **Compliance/regulatory watch:** pry-sec-filings-watch, pry-fda-recall-monitor, pry-clinical-trials-watch, pry-cve-advisory-watch, pry-sanctions-screener, pry-court-docket-monitor, pry-tender-procurement-monitor, pry-usaspending-contracts, pry-uspto-patent-monitor, pry-gdpr-cookie-checker — almost nothing comparable in the store.
- **Crypto/DeFi:** pry-chain-tvl-monitor, pry-defi-yield-monitor, pry-token-unlock-monitor, pry-whale-transfer-monitor, pry-stablecoin-flow-monitor, pry-prediction-market-monitor, pry-sports-odds-best-line — thin store coverage.
- **Infra/DevOps monitoring:** pry-ssl-cert-monitor, pry-status-page-aggregator, pry-json-api-monitor, pry-rdap-domain-watch, pry-tech-stack-detector, pry-api-docs-diff.
- **Anti-bot advantage targets:** pry-onion-site-monitor, pry-flight-price-watch, pry-hotel-rate-watch (travel sites are heavily WAF'd).

---

## 3. Gap Analysis Method

A niche qualifies if it meets ALL five gates:
1. **Demand** — people search for these scrapers (Apify ideas page, SEO terms, community requests).
2. **Gap** — few/weak existing store actors (checked against store categories + rising stars).
3. **PPE-monetizable** — a clear per-result value event exists.
4. **Anti-bot advantage** — targets sit behind WAFs (Cloudflare/Akamai/PerimeterX) where our 15-tier engine wins.
5. **Differentiation** — not duplicative of our 94 presets (checked above).

---

## 4. 15 Recommended Underserved Niches

| # | Actor name | What it scrapes | Target sites | PPE value event + price | Why underserved |
|---|---|---|---|---|---|
| 1 | `pry-app-store-rank-watch` | App Store/Play Store rankings, keyword ranks, version churn per app | apps.apple.com, play.google.com (bot-guarded) | `rank-snapshot-pulled` — $0.01 | Only generic review miners exist; rank tracking is a gap |
| 2 | `pry-appexchange-marketplace-watch` | Salesforce/HubSpot/Atlassian marketplace listings, pricing tiers, review counts | appexchange.salesforce.com, marketplace.atlassian.com (WAF'd) | `listing-extracted` — $0.02 | B2B marketplace intel has ~zero store coverage |
| 3 | `pry-ai-model-pricing-watch` | LLM API pricing pages, context windows, rate limits across providers | openai.com, anthropic.com, deepinfra.com, together.ai (Cloudflare) | `price-card-parsed` — $0.005 | Fast-moving data, no dedicated actor; AI buyers need it |
| 4 | `pry-gpu-cloud-price-watch` | GPU rental pricing/availability (H100/A100) across clouds | runpod.io, lambda.ai, vast.ai, coreweave.com | `gpu-price-pulled` — $0.005 | Exploding demand, no store actor; sites are JS-heavy + WAF'd |
| 5 | `pry-chargepoint-ev-station-watch` | EV charging station availability, pricing, outages | chargepoint.com, plugshare.com (heavy JS + bot protection) | `station-status-pulled` — $0.005 | EV data demand growing; nothing in store |
| 6 | `pry-insurance-rate-compare` | Auto/home insurance quote-page rates and coverage tiers | insurer quote funnels (Akamai-protected) | `quote-captured` — $0.03 | High-value lead data; WAF walls block generic actors |
| 7 | `pry-telecom-plan-monitor` | Mobile/broadband plan pricing, data caps, promos | carrier sites (Verizon, Vodafone, etc. — PerimeterX) | `plan-scraped` — $0.01 | Regulated, geo-fenced, bot-heavy — classic anti-bot moat |
| 8 | `pry-utility-tariff-watch` | Electricity/gas tariff pages by region, rate schedules | utility portals (geo-blocked, WAF'd) | `tariff-parsed` — $0.01 | Extends our pry-electricity-price-watch to retail tariffs; no store equivalent |
| 9 | `pry-pharma-pipeline-watch` | Drug pipeline pages, FDA approval milestones, orphan-drug designations | fda.gov, company pipelines, clinicaltrials.gov enrichment | `milestone-detected` — $0.02 | Pharma intel actors nearly absent; high willingness to pay |
| 10 | `pry-esg-scorecard-extractor` | Corporate ESG/sustainability report metrics, emissions data | corporate ESG report PDFs/pages (varied WAFs) | `metric-extracted` — $0.02 | Compliance-driven demand; PDF+table extraction is hard for generic actors |
| 11 | `pry-restaurant-availability-watch` | Reservation-slot availability, waitlists | opentable.com, resy.com (DataDome-protected) | `slot-checked` — $0.005 | DataDome-protected; generic scrapers fail; clear per-check event |
| 12 | `pry-ticket-resale-price-watch` | Resale ticket prices/fees across marketplaces | stubhub.com, seatgeek.com, ticketmaster.com (heavy anti-bot) | `price-point-captured` — $0.01 | Ticketing is the hardest anti-bot vertical; huge search demand |
| 13 | `pry-shipment-carrier-rate-watch` | Carrier shipping rate tables, surcharges (fuel, residential) | fedex.com, ups.com, dhl.com rate pages (Akamai) | `rate-table-parsed` — $0.02 | Logistics teams pay for this; sites are WAF'd; no store actor |
| 14 | `pry-ngo-grant-deadline-watch` | Grant deadlines, RFPs from foundations and government portals | grants.gov, foundation sites (mixed WAFs) | `deadline-detected` — $0.01 | Extends our scholarship/tender presets into grants; fragmented sources, no actor |
| 15 | `pry-supplier-risk-signal-watch` | Supplier distress signals: delistings, recalls, sanctions hits, news spikes across a supplier list | composite (news + registries + trade sites) | `risk-signal-emitted` — $0.02 | Supply-chain risk is a hot enterprise need; nothing in store aggregates it |

### Pricing rationale
- Commodity events (status checks, price pulls): $0.005–0.01/event — matches store PPE norms.
- High-value structured extraction (quotes, rate tables, compliance milestones): $0.02–0.03/event — justified by data value and anti-bot cost.
- All 15 have a natural "monitor mode" (scheduled runs) → recurring revenue, matching Apify's recommendation to reserve ~2h/week maintenance per public actor.

---

## 5. Notes for the Next Agent (preset builder)

- Reuse existing field helpers in `presets.py` (`URLS_FIELD`, `MAX_ITEMS_FIELD`, `PROXY_CONFIG_FIELD`, `CHANGE_THRESHOLD_FIELD`) and the `ActorSpec` pattern with named PPE events (e.g., `page-scraped`, `change-detected`).
- Monitor-style presets (1, 3, 4, 5, 8, 9, 12, 14, 15) should follow the `pry-change-monitor` shape (interval + threshold + emit events).
- Extraction-style presets (2, 6, 7, 10, 11, 13) should follow the `pry-product-data-extractor` / `pry-restaurant-menu-extractor` shape.
- Store publishing checklist (from docs): README quality, automated tests, no breaking changes, monetization = PPE with a free-tier sample run.
- [REVIEW] Prices are market-informed estimates from scraped store patterns; validate against Apify's monetization docs (docs.apify.com/actors/publishing/monetize) before setting final PPE prices.
- [REVIEW] Demand signals are inferred from store category structure, rising-stars, and the Apify ideas page reference — a keyword-volume check (e.g., via SearXNG on Talos) would strengthen gate 1 before committing build effort.
