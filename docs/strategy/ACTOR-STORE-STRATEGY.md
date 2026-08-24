# Pry Actor Store Strategy

Market analysis and pricing benchmarks for the factory presets. Pricing
arithmetic lives in `actor_factory/economics.py` (profit = 0.8 × revenue −
platform costs); this doc covers the *where to play* decisions.

## Why Pry actors win in this market

1. **Anti-bot bypass is the #1 churn driver** on Apify Store — most scrapers
   die when targets enable Cloudflare/DataDome. Pry's 12-tier adaptive chain
   with per-domain memory is structurally better than static-bypass actors.
2. **x402-native**: Apify's agentic payments require PPE + limited
   permissions. Factory actors are PPE by default → eligible for AI-agent
   discovery traffic with zero extra work.
3. **Generic extraction, no platform parsers**: we deliberately avoid
   Instagram/Amazon-specific actors (ToS arms races). Our niches are
   site-agnostic capabilities where the bypass engine IS the product.

## Preset portfolio and target niches

| Actor | Niche | Gap being filled | Price/event |
|---|---|---|---|
| pry-universal-scraper | General scraping | Firecrawl-class output w/ self-serve anti-bot | $0.004/page |
| pry-site-crawler | LLM/RAG data | Whole-site markdown corpora; crawlee-class but simpler input | $0.003/page |
| pry-screenshot-capture | Visual capture | Screenshots behind WAFs (most screenshot actors fail here) | $0.005/capture |
| pry-change-monitor | Monitoring | SimHash diffing scheduled runs; alert-style dataset | $0.001+$0.002 |
| pry-document-parser | Documents | PDF/DOCX/OCR behind bot walls | $0.006/doc |
| pry-llm-corpus-builder | **AI training data** | Clean deduped corpora for RAG/fine-tuning — fastest-growing buyer segment | $0.004/doc |
| pry-seo-site-auditor | SEO agencies | Full-site audits behind bot protection | $0.003/page |
| pry-lead-harvester | Sales/lead-gen | Public contact extraction from protected sites | $0.005/domain |
| pry-news-feed-monitor | Media/intel | RSS + full-text behind bot defenses | $0.002/article |
| pry-price-watcher | E-commerce intel | JS-rendered price tracking w/ structured-data-first parsing | $0.004/product |

## Pricing discipline (from economics.py)

- Compute cost ≈ `GB-hours × $0.4/CU`. At 512 MB–1 GB and 3–8 s/page,
  break-even lands around $0.0005–0.002/event; our prices carry ≥50% margin
  at realistic loads (`tests/test_actor_economics.py` enforces this).
- Keep the synthetic `apify-actor-start` event enabled ($0.00005) — docs
  recommend it; it offsets startup compute.
- Set memory limits in actor.json (factory emits them) to cap runaway cost.

## Quality-score playbook (docs: publishing/quality-score)

| Category | What we do |
|---|---|
| Reliability | Daily platform test survives: every preset prefills stable URLs (example.com), finishes <5 min, non-empty dataset guaranteed |
| Ease of use | Every input documented; linter enforces descriptions |
| Pricing transparency | PPE everywhere; pricing tables auto-rendered into READMEs |
| Trustworthiness | Limited permissions; memory limits declared |
| Congruency | Linter checks domain-noun alignment across title/description/events |

## Launch sequence (PUBLISH LOCKED — nothing live until org exists)

> **Status:** catalog is 79 presets @ v1.1, all store-standard packaging,
> lint-clean, tests green. NOTHING is on the Apify platform except the
> review actor `pry-recipe-miner` (build 1.0.27). Publishing is armed but
> locked: CI publish job runs on manual dispatch only
> (`.forgejo/workflows/apify-actor.yml`), and batch push waits for the org.

### Pre-flight (one-time, when the Apify org is created)

1. **Org + token**: user creates the Apify org; verify `apify info` sees it.
2. **Secret**: set `APIFY_TOKEN` in Forgejo repo secrets (CI publish job).
3. **Dry-run the batch**: `python scripts/apify-push-all.py --org <slug> --dry-run`
   → staging + validation only, zero uploads.
4. **Smoke push**: `--only pry-recipe-miner` first; confirm build succeeds
   under the org (`<slug>~pry-recipe-miner`).

### Store-listing checklist (per actor, before flipping to public)

| Item | Where | Done when |
|---|---|---|
| Title + description | actor.json / README | Linter-clean, search terms baked in ("scraper", "crawler", "monitor", "LLM", "SEO") |
| Logo/icon | .actor/ icon assets | Rendered glyph present (icon system: commit 8eef1ad) |
| Categories | Console listing form | Primary category matches processor family |
| Monetization | Console → Monetization | PPE events enabled per preset (names/prices from presets.py); synthetic `apify-actor-start` kept |
| Sample output | input schema prefill | Example run finishes <5 min with non-empty dataset (linter-enforced) |
| Permissions | actor.json | Limited permissions + memory limits declared |
| README | generated | Pricing table + FAQ rendered (human-voice pass) |
| Publish button | Console | Actor visible in Store after publish |

### Batch rollout

5. **Batch push**: `python scripts/apify-push-all.py --org <slug>` (supports
   `--only`, `--resume`, results.json incremental resume). Wave order:
   flagship 10 niches first (table above), then remaining presets.
6. **Enable PPE** in Console per preset as each lands.
7. **Monitor** Console > Insights > Analytics: revenue/cost/profit per
   actor; kill or reprice anything trending negative within the first week.
8. **Iterate**: niche FAQs and description polish are already in (human-
   voice pass); revisit pricing monthly against economics.py margins.
