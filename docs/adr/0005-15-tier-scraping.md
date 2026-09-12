# ADR 0005: 15-Tier Scraping Fallback

**Status:** Accepted
**Date:** 2026-08-26

## Context

Pry's scraping engine had 12 tiers. Competitors (Firecrawl, Scrapling) have 2-4 tiers. To maintain our moat, we needed more diverse fallback strategies.

## Decision

Expand to 15 tiers with AI-powered and API-discovery methods.

### Tier Architecture

| Tier | Method | Type |
|------|--------|------|
| 1-2 | Direct HTTP, TLS fingerprint | Network |
| 3-4 | cloudscraper, FlareSolverr | Cloudflare bypass |
| 5-7 | undetected-chromedriver, Camoufox, Playwright | Browser |
| 8-9 | Googlebot UA, Tor | Identity |
| 10 | Premium proxy | Network |
| 11-12 | Archive.org, Google Cache | Cached |
| 13 | AI Visual Scraper | Screenshot + LLM |
| 14 | Mobile App API | API discovery |
| 15 | GraphQL API Discovery | API discovery |

### Adaptive Ordering

`resilience.DomainTierMemory` promotes proven-best tiers per domain and demotes failing ones.

## Consequences

- **Positive:** Best-in-class anti-detection (no competitor has >4 tiers)
- **Positive:** AI visual scraping works on JS-heavy/canvas pages
- **Positive:** API discovery finds easier data paths
- **Negative:** More dependencies to manage
- **Negative:** AI visual requires LLM API key for full functionality
