# Apify Market & Pricing Analysis
_Scraped live from apify.com store pages, 2026-08-24. Method: store search
API for competitor discovery + full-page scrapes extracting PPE price badges
(`$X / 1,000 results`) and rental prices. Raw data: competitor-monetization
scrape archived in session knowledge._

## Market price benchmarks (per 1,000 results)

| Competitor | Vertical | Price |
|---|---|---|
| apidojo/youtube-scraper | video | $0.50 |
| compass/google-maps-reviews | reviews | $0.30 (+$29/mo rental) |
| fatihtahta/reddit-search | social | $1.19 |
| compass/google-maps-scraper | maps/leads | $1.50 |
| tri_angle/yelp-scraper | reviews | $1.50 |
| code_crafter/leads-finder | leads | $1.50 |
| clockworks/tiktok-scraper | video | $1.70 |
| streamers/youtube-scraper | video | $2.40 |
| junglee/amazon-bestsellers | e-commerce | $3.20 |
| radeance/similarweb-scraper | intel | $5.00 |
| dev_fusion/linkedin-profiles | leads | $10.00 |
| afanasenko/instagram-profiles | social | $10.00 |
| pintostudio/youtube-transcripts | content | $10.00 |

**Market bands:** budget $0.30-0.50 · mid $1.19-3.20 · premium $5-10

## Our pricing structure (79 Actors)

| Tier | Price/result | Per 1,000 | Actors | Rationale |
|---|---|---|---|---|
| T1 API-backed | $0.0005 | **$0.50** | 11 | Ties the cheapest actor on the platform; zero anti-bot cost = sustainable margin; no direct competitors for most |
| T2 Monitors | $0.0010 | **$1.00** | 26 | Recurring-run volume play; undercuts every monitoring comparison |
| T3 Extract/Audit/Tech/Leads | $0.0015 | **$1.50** | 33 | Matches compass/yelp headline while delivering multi-entity structured output + honest skip-reporting they don't have |
| T4 Browser-escalation | $0.0030 | **$3.00** | 9 | Undercuts amazon-tier ($3.20) with broader capability; far below linkedin/instagram $10 tier |
| Success premium | $0.0020 | $2.00 | change-detected only | Charge more for the valuable moment (an actual change), less for quiet checks |

## Why we win, not just compete
1. **Undercut every direct comparison** - our headline per-1k price is at or
   below the strongest competitor in each vertical.
2. **Structured > raw** - JSON-LD entities and typed dataset views vs
   competitors' HTML dumps at the same price.
3. **Honest billing surface** - skipped pages are reported with reasons;
   buyers can audit exactly what they paid for.
4. **Reliability tiers are explicit** - API-backed actors advertise their
   data source in the README; no silent breakage.
5. **80% PPE revenue share** keeps every tier profitable after compute:
   worst case (T1, 512MB, ~2s/item) platform cost ≈ $0.000013/item vs
   $0.0005 revenue = ~37x coverage.
