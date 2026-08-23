# Pry Actor Factory — Methodology

Churn out spec-compliant, **monetizable** Apify actors from Pry's scraping
engine in minutes, not days. Verified against Apify documentation
(actor.json v1, input schema v1, pay-per-event) on 2026-08-23.

## Why a factory

Every Apify actor needs the same 20% (spec files, Dockerfile, PPE billing
loop, spending-limit handling, abort flushing) and a different 80% (what it
does to each URL). The factory owns the 20% once, correctly; you write only
the per-URL logic.

```
ActorSpec (typed) ──generate_actor()──> .actor/ package
     │                                      │
     │ presets.py (5 flagship products)      ├── actor.json (v1 spec)
     │                                      ├── INPUT_SCHEMA.json
     │                                      ├── Dockerfile (pinned lock)
     │                                      ├── README.md (store-facing)
     │                                      └── src/main.py → PPEScraperRunner
     └── PricingEvent[] ───────────────> PPE billing wired by default
```

## The three-layer testing methodology

| Layer | What | Where |
|---|---|---|
| 1. Spec | Apify rules as code: version `[N].[N]`, synthetic-event guard, browser memory floor ≥512 MB, editor whitelist | `tests/test_actor_factory.py::TestSpecValidation` |
| 2. Generation | All presets produce valid packages; byte-deterministic output; embedded vs standalone schema lockstep | `TestGeneration` |
| 3. Runtime | PPE billing against a **mocked Actor SDK**: charge-per-item, spending-limit stop, error-item charging, abort flush, runaway cap | `TestPPERuntime` |

Layer 3 is the money-critical one: the mocked `FakeActor` models platform
semantics exactly — once the user spending limit is reached, `push_data`
**stops saving items** (docs: "Actor.pushData() stops pushing data over the
limit"), so the boundary item is never counted or billed.

## PPE rules encoded in the runtime

1. **Charge via `push_data(item, event_name)`** — save + bill atomically.
2. **Error items are charged too** — work done is work billed, transparently
   (`status: "error"` items land in the dataset).
3. **Stop on `event_charge_limit_reached`** — respect user budgets.
4. **ABORTING handler registered** — flushes pending work in the 30s window.
5. **Never manually charge synthetic events** — `PricingEvent.__post_init__`
   rejects `apify-actor-start` / `apify-default-dataset-item`; the platform
   bills those automatically.

## Churning out a new actor

```python
from actor_factory import ActorSpec, InputField, PricingEvent, generate_actor

spec = ActorSpec(
    name="pry-ecommerce-price-watch",
    title="Pry E-commerce Price Watch",
    description="Track product prices behind anti-bot walls.",
    version="1.0",
    inputs=(
        InputField(name="urls", title="Product URLs", type="array",
                   editor="requestListSources", required=True,
                   prefill=[{"url": "https://example.com/p/1"}]),
        InputField(name="currency", title="Currency", type="string",
                   editor="select", enum=["USD", "EUR"], default="USD"),
    ),
    pricing_events=(
        PricingEvent(name="price-checked", title="Price checked",
                     description="One product price captured.",
                     price_usd=0.002),
    ),
)
generate_actor(spec, Path("actors/price-watch"))
```

Then: override `PPEScraperRunner.process_url` for the per-URL logic, run
`apify run --purge` locally, `apify push` to ship.

## Flagship presets (`actor_factory/presets.py`)

| Actor | Primary event | Price | Use case |
|---|---|---|---|
| pry-universal-scraper | `page-scraped` | $0.004 | Markdown for any URL |
| pry-site-crawler | `page-crawled` | $0.003 | Whole-site LLM corpora |
| pry-screenshot-capture | `screenshot-taken` | $0.005 | Visual capture behind WAFs |
| pry-change-monitor | `page-checked` + `change-detected` | $0.001 + $0.002 | Scheduled diffing |
| pry-document-parser | `document-parsed` | $0.006 | PDF/DOCX/OCR |

Pricing follows the docs' profit formula: `profit = 0.8 × revenue − platform
costs`. Enable the synthetic `apify-actor-start` event in Console to offset
startup costs; set memory limits (already emitted into actor.json) to cap
runaway compute.

## Agentic payments (x402) eligibility

Per Apify docs, actors become eligible for agentic payments (AI agents pay
without Apify accounts) when they: use PPE (✓ factory default), run with
limited permissions, and don't use Standby mode. Pry's x402-native core
makes this a natural fit — keep actors PPE and permission-light.

## CI

`.forgejo/workflows/apify-actor.yml`: validates packaging, runs all three
test layers, builds the Docker image, publishes on main when `APIFY_TOKEN`
is configured.
