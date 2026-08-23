# Monetization Review — Currently-Free Routes (business decision doc)

Date: 2026-08-23 · Context: the x402 gate is now fail-closed (every route
explicitly classified). 188 routes are free by explicit allowlist. This doc
categorizes them by cost profile and proposes which are monetization
candidates. **Decision needed from business; engineering executes the
pricing move in ~1h per batch once approved** (add op to X402_PRICING +
PAID_ENDPOINTS, drop from DEFAULT_FREE_PATHS, client notice).

## Batch A — STRONG candidates (expensive browser/data ops, direct Firecrawl-class analogues)

| Route family | Why paid | Suggested op | Price anchor |
|---|---|---|---|
| `/v1/screenshot` | Headless browser render per call | `screenshot` | $0.002 (scrape tier) |
| `/v1/ocr/extract` | CPU-heavy OCR | `ocr_extract` | $0.005 |
| `/v1/vision` (+/models stays free) | LLM vision calls = real token cost | `vision` | pass-through + margin |
| `/v1/camoufox/fetch` | Full stealth browser session | `camoufox_fetch` | $0.01 (stealth tier) |
| `/v1/tls/impersonate`, `/v1/tls/rotate` | TLS spoofing infra cost | `tls_impersonate` | $0.005 |
| `/v1/shadow-dom` | Browser automation | `shadow_dom` | $0.002 |
| `/v1/email/{gmail,outlook,scrape}`, `/v1/emails` | Deep scraping, high value | `email_scrape` | $0.005 |
| `/v1/marketplace/{amazon,walmart,tiktok}/*` | Product data = direct revenue analogue | `marketplace_*` | $0.005 |
| `/v1/social/{platform}/{handle}` | Profile scraping | `social_profile` | $0.005 |
| `/v1/intel/*` (analyze/report/snapshot) | Multi-source aggregation | `intel_report` | $0.01 |
| `/v1/health/*` (drug/insurance/trials) | Regulated-data scraping | `health_data` | $0.005 |

## Batch B — MODERATE candidates (cheap but metered-value)

`/v1/extract*`, `/v1/parse`, `/v1/markdown`, `/v1/schema*`, `/v1/enrich*`,
`/v1/summarize`, `/v1/categorize`, `/v1/compare`, `/v1/diff`, `/v1/suggest`,
`/v1/dedup/check`, `/v1/seo*`, `/v1/structure/*`, `/v1/reconcile*`,
`/v1/training/*`, `/v1/export`
→ These run on already-fetched content. If the fetch was paid, transform is
margin on sunk cost: consider a single `$0.001 transform` op or keep free as
retention perk. Recommend: keep free for now, revisit after Batch A data.

## Batch C — KEEP FREE (control plane / legal / growth)

- Infra: `/health`, `/live`, `/ready`, `/metrics`, `/version`, docs/OpenAPI
- Payment flow: `/v1/x402/*` (chicken-and-egg)
- Control plane: sessions, jobs, streams, proxy mgmt, cookies, breaker,
  config, capabilities, diagnostics, pipelines, recordings, reviews,
  webhooks mgmt, alerts, destinations, CRM/commerce sync, referrals,
  costing/freshness/quality dashboards, actors/agency registry, signup
- Legal obligation: `/v1/gdpr/*` (charging for erasure is a compliance smell)
- Growth loops: `/v1/share`, `/share/{id}`, `/v1/ai/*manifests`

## Execution checklist (per batch)

1. Add operation to `X402_PRICING` (x402/scheme.py or middleware setdefault block)
2. Move path prefix from `DEFAULT_FREE_PATHS` to `PAID_ENDPOINTS`
3. Startup audit enforces classification automatically (no other changes)
4. Update pry_sdk/pry_mcp tool pricing metadata + CHANGELOG + client notice
5. Watch `pry_requests_total{status="402"}` for client breakage for 48h

## Decision requested

Approve Batch A (yes/no/per-family), pick price anchors, choose cutover
(immediate vs deprecation window). Engineering lead-in once decided: ~1 day
including SDK/docs/tests.
