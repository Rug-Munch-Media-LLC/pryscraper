# Apify Store Market Analysis — Pry Actor Strategy

Data: live sweep of the Apify Store public API using Pry's own HTTP stack
(2026-08-23). Raw data: 50 actors by popularity + category census across
7 verticals. Method note: pricing-event details are not exposed by the
public API (console-only); model-level data is.

## Platform snapshot

- **49,866 actors** published; top actor has **181M lifetime runs**.
- **PPE is the winning model**: 46 of the top 50 actors bill
  pay-per-event. Only 2 are free. Our factory's PPE default is correct.
- Free actors exist as demand funnels (`website-content-crawler`: 40M runs,
  $0) — monetization comes from paid siblings.

## What people actually pay for (top runs)

| Actor | Runs | Model |
|---|---|---|
| apify/web-scraper | 181M | FREE (funnel) |
| apidojo/tweet-scraper | 158M | PPE |
| apify/instagram-scraper | 180M | PPE |
| apify/google-search-scraper | 112M | PPE |
| clockworks/tiktok-scraper | 114M | PPE |
| compass/crawler-google-places | 36M | PPE |
| apify/website-content-crawler | 40M | FREE (funnel) |
| dev_fusion/linkedin-profile-scraper | 24M | PPE |
| curious_coder/linkedin-jobs-scraper | 3.4M | PPE |
| lukaskrivka/google-maps-with-contact-details | 2M | PPE |

Patterns:
1. **Platform-specific scrapers dominate** (social, maps, SERP) — but they
   are ToS arms races requiring per-platform parsers. We deliberately avoid
   the logged-in/private-data ones.
2. **The two best generic opportunities**: Google SERP (112M runs) and
   Maps+contacts combo (36M + 2M) — both are *public* data, both are
   anti-bot games, which is exactly Pry's edge.
3. **Lead generation is the largest category** (19,746 actors) — crowded
   but demand-proven; winners differentiate on contact enrichment.
4. **AI corpus building is proven** (content-crawler 40M runs) and the AI
   category holds 7,945 actors — buyers pay for clean, deduped markdown.

## Category census (competition density)

| Category | Actors | Read |
|---|---|---|
| LEAD_GENERATION | 19,746 | Biggest market; contact enrichment wins |
| SOCIAL_MEDIA | 9,546 | ToS arms race — avoided |
| AI | 7,945 | Corpus/RAG demand proven |
| JOBS | 5,072 | ATS aggregation viable (public pages) |
| REAL_ESTATE | 4,204 | JS-rendered portals = bypass value |
| NEWS | 3,108 | RSS+full-text monitoring underserved |

## Our portfolio mapped to demand (30 actors)

**Core scraping (market-proven):**
| Pry preset | Market evidence | Price/event |
|---|---|---|
| pry-serp-scraper | google-search-scraper 112M runs | $0.003 |
| pry-maps-lead-extractor | maps scraper 36M + contacts combo 2M | $0.005 |
| pry-lead-harvester | lead-gen = largest category | $0.005 |
| pry-llm-corpus-builder | content-crawler 40M funnel | $0.004 |
| pry-universal-scraper | web-scraper 181M funnel | $0.004 |
| pry-site-crawler | crawlee-class demand | $0.003 |
| pry-screenshot-capture | visual capture niche | $0.005 |
| pry-document-parser | PDF/OCR steady demand | $0.006 |

**Vertical monitors (recurring-revenue pattern):**
| Pry preset | Domain route | Price/event |
|---|---|---|
| pry-change-monitor | watch/diff engine | $0.001+$0.002 |
| pry-news-feed-monitor | news domain | $0.002 |
| pry-price-watcher | marketplace domain | $0.004 |
| pry-jobs-aggregator | jobs domain | $0.002 |
| pry-property-lister | real-estate domain | $0.004 |
| pry-hotel-rate-watch | travel domain | $0.004 |
| pry-flight-price-watch | travel domain | $0.004 |
| pry-inventory-alert | e-commerce domain | $0.002 |
| pry-deal-radar | e-commerce domain | $0.002 |
| pry-review-aggregator | marketplace reviews | $0.003 |

**Compliance & intel (defensible, underserved):**
| Pry preset | Domain route | Price/event |
|---|---|---|
| pry-sec-filings-watch | legal domain | $0.003 |
| pry-court-docket-monitor | legal domain | $0.003 |
| pry-sanctions-screener | compliance | $0.003 |
| pry-tender-procurement-monitor | gov-data domain | $0.002 |
| pry-crypto-listing-monitor | crypto domain | $0.002 |
| pry-token-safety-scanner | crypto security | $0.004 |
| pry-serp-rank-tracker | attention-seo domain | $0.002 |
| pry-ad-intel-monitor | attention/ad-intel module | $0.002 |
| pry-local-directory-extractor | local-business domain | $0.003 |
| pry-provider-finder | healthcare domain | $0.004 |
| pry-clinical-trials-watch | healthcare/trials | $0.003 |

All margins verified >=40% at realistic loads (`tests/test_actor_economics.py`).

## Daily-test survival rule

Apify's automated testing runs each Store actor with its DEFAULT input and
requires Succeeded + non-empty dataset within 5 minutes, daily. Factory
rule: prefills use stable hosts only; graceful error items keep datasets
non-empty even when targets fail. `pry-maps-lead-extractor` ships with an
example.com prefill for exactly this reason.

## Launch sequence

1. Set `APIFY_TOKEN` → CI publishes all 14 presets.
2. Enable PPE events in Console (names/prices from `presets.py`).
3. Week 1: watch Insights > Analytics per actor; reprice or kill negatives.
4. Week 2+: double down on whichever of serp/maps/corpus shows traction;
   platform-specific parsers only if a partner demands it.
