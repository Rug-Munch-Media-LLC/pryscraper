# 15-Tier Fallback Chain

Pry's scraping engine routes each request through an adaptive 15-tier fallback chain, escalating only as far as the target requires.

## Tier Architecture

| # | Tier | Method | When Used |
|---|------|--------|-----------|
| 1 | Direct HTTP | Smart headers, rotating UAs | Default for simple sites |
| 2 | TLS Fingerprint | curl_cffi JA3/JA4 bypass | TLS fingerprinting detected |
| 3 | cloudscraper | Python-native Cloudflare bypass | Light Cloudflare |
| 4 | FlareSolverr | Cloudflare/WAF bypass service | Heavy Cloudflare |
| 5 | undetected-chromedriver | Modified Chrome, no detection | Chrome-required sites |
| 6 | Camoufox | Stealth Firefox, source-level anti-fingerprinting | Firefox-required sites |
| 7 | Playwright Stealth | Full browser with human behavior | JS-heavy SPAs |
| 8 | Googlebot UA | Search engine crawl mimic | Bot detection |
| 9 | Tor Proxy | Anonymous routing via SOCKS5 | IP blocking |
| 10 | Premium Proxy | Paid residential proxies | Geographic restrictions |
| 11 | Archive.org | Wayback Machine cached version | Dead pages |
| 12 | Google Cache | Google's cached version | Last resort |
| 13 | AI Visual | Screenshot + LLM vision extraction | Canvas/WebGL rendering |
| 14 | Mobile App API | Impersonate mobile clients | Mobile-only APIs |
| 15 | GraphQL Discovery | Find and query GraphQL endpoints | Modern web apps |

## Adaptive Ordering

`resilience.DomainTierMemory` promotes proven-best tiers per domain and demotes failing ones. Each domain gets an intelligent, self-improving fallback chain.

## Block Signal Detection

`detect_block` module classifies:
- CAPTCHA pages → jump to FlareSolverr/Playwright
- WAF challenges → jump to Camoufox/Tor
- Rate limits → jump to premium proxy/Tor

## Circuit Breakers

Flaky upstream services stop wasting your latency budget. After 3 failures, a tier is skipped for 5 minutes.

## Configuration

```bash
# Disable specific tiers
PRY_DISABLE_TIERS=tor,premium_proxy

# Set tier timeout (seconds)
PRY_TIER_TIMEOUT=30

# Enable/disable adaptive ordering
PRY_ADAPTIVE_TIER=true
```
