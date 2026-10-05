# Method Memory — per-domain scrape-approach intelligence

Status: design only (no code). Date: 2026-09-26. Track: `feat/method-memory`.

## 0. Executive summary

Pry **already has ~60% of this** in `pry.engine.resilience.DomainTierMemory`, and it is
**already wired** into the read path (`scraper_orchestrate.py:165`) and the write path
(`scraper_orchestrate.py:385`). The right answer is **not a new subsystem** — it is
hardening and completing the one that exists, then filling four specific holes:

| # | Hole | Severity |
|---|------|----------|
| A | No **cost** dimension — engine has zero cost accounting (`grep cost_usd src/pry/engine/` → nothing) | High |
| B | No **block-shape** memory — `BlockSignal.kind` is detected but never written to domain memory | High |
| C | Memory keyed on **registrable domain** only — `example.com/blog` and `example.com/shop` share one record | Medium |
| D | Volatile by default — persistence is **opt-in via env** (`PRY_RESILIENCE_PERSIST=1`), so prod loses it on restart | High |

Plus two correctness issues in the existing scoring, and a second disconnected
taxonomy (`engine/methods/registry.py`) that never enters the tier chain.

## 1. What already exists (inventory — do not rebuild)

### 1.1 `pry.engine.resilience.DomainTierMemory` — the memory core (469-line module)

Already implemented and unit-tested (`tests/test_resilience.py`, 20+ tests):

- `TierRecord`: `successes`, `failures`, `last_success_at`, `last_failure_at`, `total_latency`
- `score` property = `success_rate + recency * 0.5` (recency decays over `DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600`)
- `record(domain, tier, success, latency)` — write
- `best_tier(domain, candidates)` — read, single winner
- `reorder_for_domain(domain, candidates)` — read, full chain reorder
- `ResilienceRegistry` — global singleton `registry`, optional JSON persistence
  (`resilience_state.json`), throttled save, `atexit` flush, never-raises I/O

Existing policy constants (`resilience.py:33-50`):

```
DOMAIN_MEMORY_MAX_AGE_SECONDS  = 3600
DOMAIN_FAILURE_SKIP_MIN_SAMPLES = 3
DOMAIN_FAILURE_SKIP_RATE       = 0.30
DOMAIN_TIER_COOLDOWN_SECONDS    = 300.0
DOMAIN_MEMORY_SAVE_INTERVAL    = 10.0
```

### 1.2 The read path — already correct

`scraper_orchestrate.py::_scrape_with_fallbacks`:

```python
tier_order = self._build_tier_order(proxy_url, premium_first)  # L158 static 15-tier baseline
name_to_fn = dict(tier_order)
ordered_names = registry.reorder_for_domain(domain, [n for n, _ in tier_order])  # L165
tier_order = [(n, name_to_fn[n]) for n in ordered_names]  # L166
```

Per-domain semaphore wraps the whole call (`scrape()`, L~110). Circuit breakers
(`BREAKER_FOR_TIER` → flaresolverr/playwright/camoufox/tls_fingerprint) skip dead services.

### 1.3 The write path — already correct

`scraper_orchestrate.py::_record_tier_outcome` (L375-389) is called for **every** tier attempt
with `success` and `latency`, then feeds Prometheus `SCRAPE_LATENCY`.

Critical detail already handled: `success = False` when `signal.kind != "none"` (L195-198) —
**a block page never counts as a success.** `_promote_preferred_tiers` also in-flight
reorders on the current attempt using `_PREFER_ON_BLOCK` (L85-90).

### 1.4 `pry.engine.fallback_telemetry` — the observability twin

`FallbackRecord` already captures the full journey: `domain`, `tier_order`, per-attempt
`{tier, success, error, duration_ms}`, `final_tier`, `success`, `duration_ms`.
`get_domain_stats(domain)` already computes per-tier success rate + avg duration.
Exposed at `GET /v1/diagnostics`.

**But:** it is a `deque(maxlen=500)` ring buffer in-process. It is a *diagnostics* surface, not
a memory — nothing reads it to make decisions, and it dies with the process.

### 1.5 Two other adaptive surfaces (adjacent, not method memory)

- `engine/adaptive_selector.py` — Scrapling-style **selector** relocation + `PageSignature`
  structural change detection. This is *what to extract*, not *how to fetch*. Complements.
- `engine/adaptive.py` — `AdaptiveCrawler`, information-foraging crawl-stop. Unrelated axis.

### 1.6 A second, disconnected method taxonomy

`engine/methods/registry.py` `METHODS` dict: `hidden_api_discovery`, `persistent_session`,
`render_wait`, `feed_parsing`, `sitemap_discovery`, `graphql_discovery`, `paginated_crawl`.
Each has `when` / `cost` / `notes` metadata. **It is not referenced by the tier chain at all**
— only re-exported by `scraping_methods.py`. This is a real problem: the two taxonomies
(15 fallback tiers vs 7 method modules) never meet, so "the right method" is unlearnable
across them.

### 1.7 Gaps confirmed by search

- **No cost in the engine.** `grep -rn "cost_usd|price_usd" src/pry/engine/` → 0 hits.
  x402 prices live only in the API layer (`api/routers/commerce/x402.py`, `X402_PRICING`).
- **No block-shape memory.** `BlockSignal.kind` is returned in the scrape result
  (`result["block_signal"]`) and used in-flight, never persisted per domain.
- **No paywall/CAPTCHA-vendor model** beyond the 6 `kind`s in `block_detection.py`.
- **Domain key is `parsed.netloc`** (L133) — includes port, not registrable domain.
- **Persistence off by default** (`default_state_path()` returns `None` unless
  `PRY_RESILIENCE_PERSIST=1` or `PRY_RESILIENCE_STATE` set).
- **Cache is content-only.** `core/cache.py` `ResponseCache` = LRU(500) + optional Redis
  (`pry:cache:{md5}`), TTL 300s, stores response bodies. Not a method store.
- **DB has no method table.** `core/db/models_scraping.py` (183 lines) has Quality/Intel/
  Structure/Monitors/Accounts/Sessions/Reports/Pipelines/Webhooks. No per-domain method memory.
- **8 alembic migrations**, latest `0007_add_x402_ledger_tables.py` + `b3b4faf8…`.

## 2. Architecture

### 2.1 Where memory lives — three tiers

| Tier | Store | Holds | Latency budget |
|------|-------|-------|----------------|
| **L0 hot** | Redis hash `pry:methodmem:{domain}` | rolling counters + last-seen + shape, TTL 30d | <1ms |
| **L1 durable** | Postgres `method_memory` + `method_memory_events` | full event log, durable | async, batched |
| **L2 archive** | Qdrant (RugBrain `known_scams`/`threat_intel_v2`-style collection `pry_method_memory`) | embeddings of block shapes for *new* domains with no history | async |

Read is **L0 → L1 → cold-start**. Postgres is authoritative; Redis is a write-through cache
that can be flushed at any time. Qdrant is *not* on the hot path — it only answers
"what does a domain like this one look like?" when memory is empty.

This reuses the `ResponseCache` degrade-gracefully pattern (L1 in-memory, L2 Redis, never raise)
and mirrors `core/cache.py:56-70` semantics for a different key space.

### 2.2 Schema

**Postgres — `method_memory` (one row per domain, the selection surface)**

```python
class MethodMemory(Base):
    __tablename__ = "method_memory"
    id = Column(Integer, primary_key=True)
    domain = Column(String(256), unique=True, index=True, nullable=False)  # registrable
    # per-method stats, JSON: {"direct": {"ok": 12, "fail": 1, "p50_ms": 180,
    #                     "p95_ms": 900, "cost_usd": 0.0, "last_ok": 1737..., "last_fail": 0}}
    stats = Column(JSON, default=dict)
    # best known method, denormalised for a single-row read
    best_method = Column(String(32), default="", index=True)
    best_score = Column(Float, default=0.0)
    # bot-wall shape: {"kinds": {"cloudflare": 9, "captcha": 2},
    #                  "vendor": "cloudflare", "confidence": 0.95, "paywall": false,
    #                  "last_kind": "cloudflare", "seen_at": 1737...}
    block_shape = Column(JSON, default=dict)
    # ordered full chain (learned), not just the winner
    learned_order = Column(JSON, default=list)
    samples = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)  # 0..1, how much we trust this row
    first_seen_at = Column(DateTime, default=_now)
    last_seen_at = Column(DateTime, default=_now, index=True)
    last_success_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)  # TTL anchor
```

**Postgres — `method_memory_events` (append-only, the feedback loop's raw material)**

```python
class MethodMemoryEvent(Base):
    __tablename__ = "method_memory_events"
    id         = Column(Integer, primary_key=True)
    domain     = Column(String(256), index=True, nullable=False)
    method     = Column(String(32), index=True, nullable=False)  # tier name
    success    = Column(Boolean, nullable=False)
    latency_ms = Column(Float, default=0.0)
    cost_usd   = Column(Float, default=0.0)
    # shape observed on THIS attempt: block kind, status, paywall flag
    block_kind = Column(String(32), default="")
    block_conf = Column(Float, default=0.0)
    evidence   = Column(JSON, default=list)   # capped evidence markers
    reason     = Column(String(64), default="")  # won | blocked | empty | invalid | timeout
    target_path= Column(String(64), default="")  # path-shape bucket, see 2.3
    ts         = Column(DateTime, default=_now, index=True)
    Index("ix_mme_domain_ts", "domain", "ts.desc())
```

Partition/retention: `method_memory_events` older than 30d is dropped by a maintenance
pass; `method_memory` rows with `expires_at < now()` are swept weekly.

### 2.3 Keying — fix the domain granularity (gap C)

Read path currently uses `parsed.netloc` (L133). That conflates `/blog` with `/shop` on the
same host, which routinely have different bot walls. Two keys:

- `domain` = **registrable** domain (eTLD+1) — the memory/rollup key, sharing stats across
  subdomains where the wall is host-wide.
- `scope`  = `domain + path-shape bucket` — the *selection* key.

Path-shape buckets keep cardinality bounded: `""` (homepage), `/product/*`, `/blog/*`,
`/api/*`, `/search*`, `/account*`, `/checkout*`, else first path segment.

Selection tries `scope` first; on `< MIN_SAMPLES` it falls back to `domain`; below that,
cold-start. Reuse the existing `engine/url_key.py` (49 lines) if it already hashes
comparable shapes — **[REVIEW]** confirm its contract before reusing.

### 2.4 Write path

Single choke point — **`_record_tier_outcome` (`scraper_orchestrate.py:375`)**. Every tier
attempt already funnels through it, so this is the only place to touch.

1. Widen the signature to carry the observation, not just the verdict:
   `record(domain, method, success, latency_ms, cost_usd, block_kind, block_conf, evidence, reason, scope)`.
2. **Cost** comes from a new `engine/tier_cost.py` table of per-tier unit costs
   (`direct: 0.0`, `tor: 0.0`, `premium_proxy: <from settings>`, `camoufox: <cpu-sec>`,
   `flaresolverr: 0.0`+latency, `actor:<slug>: <from actor_factory.economics>`), multiplied
   by observed usage (proxy bytes / browser-seconds / actor compute-seconds).
3. `reason` replaces the current boolean with a *why*: `won` | `blocked:<kind>` | `empty`
   | `invalid` | `timeout` | `error:<class>`. Derived from the already-computed
   `BlockSignal` + `_is_valid` + the exception branch in `_attempt_tier`.
4. Emit to three sinks, **all best-effort, none on the correctness path**:
   - Redis `HINCRBY`/`HSET` (async, fire-and-forget task) — L0
   - in-process `deque(maxlen=500)` — replaces/feeds `fallback_telemetry` ring
   - Postgres insert — queued to a small background writer with a batched flush
     (never `await` inline; the engine hot loop must not gain a DB round-trip)

Guard the whole thing: any exception → log at debug, continue. Same contract as
`tiers_base._record_telemetry`.

### 2.5 Read / selection path

Replaces `DomainTierMemory.reorder_for_domain` as the authority (keep it as the
in-process fast path + the fallback when Redis/PG are cold).

**Selection score** — replace the current `success_rate + recency*0.5` with an
explicit utility that includes cost and latency, because the whole point is to avoid
paying for Camoufox when `direct` works:

```
utility(m) = w_s·confidence(m)          # successes / (successes + failures), Laplace-smoothed
           + w_r·recency(m)             # exp decay, τ = 24h
           − w_l·norm_latency(m)        # log-scaled p50 against the domain's own fastest tier
           − w_c·norm_cost(m)           # cost_usd / domain's cheapest observed
           + w_s·shape_fit(m)           # does m address the last observed block kind?
w = {success 0.5, recency 0.2, latency 0.1, cost 0.15, shape_fit 0.05}
```

`shape_fit` is the genuinely new term: if the last three attempts for a scope hit
`cloudflare` and `camoufox` cleared it 3/3, `camoufox` gets a bonus that `direct`
cannot earn even at 1.00 success rate.

Keep the existing safety rails intact — `DOMAIN_FAILURE_SKIP_MIN_SAMPLES`,
`DOMAIN_FAILURE_SKIP_RATE`, `DOMAIN_TIER_COOLDOWN_SECONDS`, and the "never return empty"
guarantee. They are correct and tested.

**Fix two existing scoring bugs:**

- `TierRecord.score` divides by `total` with no smoothing, so a tier with **1 success / 0
  failures** scores a perfect `1.0` — beating a battle-tested `98/100`. Laplace smoothing
  (`(ok+1)/(n+2)`) is the fix; this is the single highest-value correctness change in the design.
- The recency bonus is added to the score but the cooldown demotes separately, so a
  recently-failed-but-high-success tier gets demoted *and* carries a stale bonus. Make
  cooldown a hard filter before scoring (it already is in `reorder_for_domain` — but
  `best_tier` at L185-201 does **not** apply the skip rule, so the two readers disagree).
  Make `best_tier` delegate to `reorder_for_domain`.

### 2.6 TTL / eviction

| Object | Policy | Rationale |
|--------|--------|-----------|
| `method_memory` | `expires_at = last_seen_at + 30d`, swept weekly | a dormant domain's wall has changed; stale rows mislead |
| `method_memory_events` | 30d retention, batched delete | raw history is only useful as a rolling window |
| Redis `pry:methodmem:*` | `EXPIRE 30d` on every touch | self-cleaning; no sweeper needed |
| `DomainTierMemory` in-process | `DOMAIN_MEMORY_MAX_AGE_SECONDS = 3600` (keep) | in-process is a cache, PG is truth |
| Qdrant points | no TTL, upsert by domain | small, and the "similar domain" answer ages well |
| Cooldown entries | 300s (keep) | already correct |

**Cold-start path (no memory at all):** the existing static 15-tier order runs and
*records*, which is exactly how the first row gets built. This is already how Pry learns
today — so the design degrades safely to present behaviour.

Additionally, for a brand-new domain, Qdrant can suggest a prior: embed the domain +
detected shape, retrieve the k nearest known-bad/known-good domains, and seed the initial
order. This is the one place Qdrant earns its keep.

### 2.7 Feedback loop

```
scrape(url)
  └─ selection: method_memory(scope) → domain → cold-start order
  └─ attempt tier → BlockSignal(kind, confidence, evidence) + _is_valid + latency + cost
  └─ write: L0 Redis + ring + PG event      (async, never blocks)
  └─ on wall change (BlockSignal.kind differs from stored block_shape):
        → bump event.reason
        → mark the row `stale_shape`; promotion of the wall-clearing method is
          *accelerated* for the next K attempts (explore window)
  └─ nightly aggregation job:
        events → recompute stats (p50/p95, success, cost) → upsert method_memory
        → recompute best_method / learned_order / confidence
        → Qdrant upsert of the shape vector
  └─ weekly: TTL sweep + Qdrant dedupe
```

**Drift protection — the important bit.** Bot walls change. A row that says
"flaresolverr wins here" can become wrong and, worse, *persistently* wrong, because a wrong
row is self-reinforcing (it keeps picking the now-failing tier and keeps recording failures,
which cooldown then keeps demoting). Two guards:

1. **Explore window** — even for a confident row, always attempt the static-best cheap tier
   (`direct`) at a low rate (e.g. 1 in 20) while the row is fresh. A confirmed success
   re-promotes it immediately. Cost: ~5% overhead. Benefit: the row can never fully ossify.
2. **Shape-change detection** — a new `BlockSignal.kind` for a scope invalidates the
   `shape_fit` term and forces a bounded re-exploration (try top-3 methods once each).

---

## 3. Five highest-value MCP tools

Pry's MCP surface is **hand-declared**, not auto-derived: `pry_mcp/tools.py::PRY_TOOLS`
is the source of truth and `pry_mcp/tool_registry.py` dispatches by name. (An earlier
`api/mcp_tools.py::discover_api_tools()` claimed to walk `app.routes` and expose every
endpoint, but it saw only 4 tools because `app.routes` holds 88 router stubs rather than
expanded routes, and nothing called it; it was deleted.) So each tool also needs a
**route** in a new `api/routers/core/method_memory.py` — the two lists are maintained
separately, which is why `scripts/check-doc-claims.py` gates the counts.
Auth reuses the `_require_auth` pattern from `routers/core/diagnostics.py:25-33`.

| # | Tool | Route | Why it earns its slot |
|---|------|-------|---------------------|
| 1 | `method_memory_recommend` | `GET /v1/method-memory/{domain}` | **The read path, exposed.** "What should I use for this domain, and why?" Returns ordered chain, per-method success/latency/cost, confidence, staleness. The single tool an agent needs to *stop re-learning*. |
| 2 | `method_memory_record` | `POST /v1/method-memory/record` | **The write path, exposed.** Lets an external actor/agent report an outcome for a method it used (e.g. an Apify actor run, a Browserbase session) so its cost/quality feeds the shared model. Without it, off-server methods are invisible forever. |
| 3 | `method_memory_explain` | `GET /v1/method-memory/{domain}/explain` | Why the last scrape escalated. Returns the block shape, per-attempt reasons, which rail (cooldown / skip / promotion) fired. Turns a black box into a debuggable one — the operator-facing twin of the fallback_telemetry ring. |
| 4 | `method_memory_shape` | `GET /v1/method-memory/{domain}/shape` | Current wall profile: `{kind, vendor, confidence, paywall, captcha, evidence, seen_at}`. Directly answers "is this paywalled / behind Cloudflare / needs a captcha solver?" — a question Pry currently cannot answer for a *known* domain without a live attempt. |
| 5 | `method_memory_forget` | `DELETE /v1/method-memory/{domain}` | **Mandatory escape hatch.** A wrong row must be correctable by an operator, and an agent must be able to say "my knowledge of this domain is stale, re-learn". Also the compliance story: purge learned behaviour about a target on request. |

Deliberately **not** proposed: a generic "list all memories" bulk-dump tool (cardinality risk,
low value) and a "force a method" override tool (tool #5 + a `preferred_first` scrape option
covers it, and a force-tool invites abuse of expensive tiers).

**Monetisation:** #1 and #4 fit the existing `X402_PRICING` map
(`api/routers/commerce/x402.py:94`) as low-cost reads. Method memory is a *routing advantage* —
pricing it as a premium read is defensible and is a differentiator no competitor offers.

---

## 4. Phased build order

Each phase is independently shippable and leaves the system working.

### Phase 0 — Make the existing memory actually work (no schema)

- `docker-compose.yml` / `.env.example`: set `PRY_RESILIENCE_PERSIST=1` so the prod
  container survives restart. **Today it does not.** Cheapest possible win.
- `src/pry/engine/resilience.py`: Laplace-smooth `TierRecord.score`; make `best_tier`
  delegate to `reorder_for_domain` so both readers agree.
- `tests/test_resilience.py`: add smoothing + delegation cases.
- **Gate:** `make lint test`. **Done when** a restart preserves the order.

### Phase 1 — Add the missing dimensions (cost + shape), still in-process

- NEW `src/pry/engine/tier_cost.py` — per-tier unit cost table + cost calculator.
- EDIT `src/pry/engine/scraper_orchestrate.py`: widen `_record_tier_outcome`
  (L375) to carry cost, `block_kind`, `reason`; populate from the already-computed
  `BlockSignal` at L193-198.
- EDIT `src/pry/engine/tier_cost.py` consumers in `resilience.py` — extend `TierRecord`
  with `cost_usd`, `p50_ms`, `last_block_kind`.
- EDIT `src/pry/engine/resilience.py`: the §2.5 utility score incl. `shape_fit`.
- **Gate:** existing fallback tests stay green; new scoring tests. **Done when** a
  domain with a working `direct` stops reaching `camoufox` after warm-up.

### Phase 2 — Durable store

- EDIT `src/pry/core/db/models_scraping.py` — add `MethodMemory` + `MethodMemoryEvent`.
- NEW `alembic/versions/0008_method_memory.py` (follow `0007` naming).
- NEW `src/pry/core/method_memory_store.py` — PG read/write + aggregation job, batched,
  never on the engine hot path.
- EDIT `src/pry/engine/scraper_orchestrate.py` — read order from store, write async.
- EDIT `src/pry/engine/resilience.py` — `DomainTierMemory` becomes the L0 cache in front
  of the store, not the authority.
- **Gate:** `alembic upgrade head` + migration round-trip test; concurrency test.
  **Done when** a cold worker process picks up the learned order for a known domain.

### Phase 3 — Expose it (MCP + API)

- NEW `src/pry/api/routers/core/method_memory.py` — the 5 tools.
- EDIT `src/pry/api/routers/core/__init__.py` (or the router registry) to mount it.
- EDIT `src/pry/api/routers/commerce/x402.py` — add #1/#4 to `X402_PRICING`.
- EDIT `src/pry/api/routers/core/diagnostics.py` — fold the new store into `/v1/diagnostics`.
- **Gate:** MCP tool appears in `pry_mcp/tools.py::PRY_TOOLS`; auth test; x402 price test;
  `python3 scripts/check-doc-claims.py` still exits 0.
  **Done when** an agent can call `method_memory_recommend` over MCP and act on it.

### Phase 4 — Close the taxonomy gap + cold start

- EDIT `src/pry/engine/methods/registry.py` + `scraper_orchestrate.py::_build_tier_order`:
  fold the 7 `METHODS` entries into the learnable chain so `hidden_api_discovery`,
  `render_wait`, `feed_parsing`, `sitemap_discovery` become selectable *methods*, not
  dead metadata. This is what makes "the right method" a complete answer.
- NEW `src/pry/core/method_memory_similarity.py` — Qdrant embed of domain+shape; seed a
  new domain's initial order from k nearest known domains. **Off the hot path.**
- **Gate:** no orphan methods; cold-start suggestion is logged and rate-limited.
  **Done when** a never-seen domain gets a non-random first attempt.

### Phase 5 — Harden

- Explore window (§2.7) + shape-change invalidation, with counters in
  `core/observability.py` (`SCRAPE_COUNT`/`SCRAPE_LATENCY` already exist there; add
  `METHODMEM_PROMOTION`, `METHODMEM_EXPLORE`, `METHODMEM_COLDSTART`).
- TTL sweeper + event retention job.
- Grafana dashboard: promotion/demotion churn, stale-row count, cost per successful scrape.
- **Done when** a metric exists for "rows that were wrong and got corrected" — the
  honest measure of whether the memory is helping or ossifying.

---

## 5. Comparison: Firecrawl / Apify / Browserbase

### 5.1 What they actually do

| | Firecrawl | Apify (Crawlee) | Browserbase |
|---|---|---|---|
| Method selection | Per-request `formats` + `actions`; server tries a pipeline. Some adaptive behaviour, **stateless across requests** | `CrawlingContext` is per-**run**; session pool, proxy rotation, `RequestHandler` retries. Memory dies with the run | Stealth browser sessions + proxies. Per-session, not per-domain |
| Caching | **Content** cache: `maxAge` default 48h, `minAge` cache-only, `storeInCache` (docs: `/features/scrape`) | Dataset/key-value store, user-managed | Session replay, not result cache |
| Wall handling | Proxy geo-selection, `enhanced` mode (per docs: "better success rates while maintaining privacy") | Proxy rotation + `SessionPool` + blocking-retry callbacks | Stealth + residential/ISP proxies — the actual product |
| Cost | Credits: 1 base/page, +4 for json/question/highlights/PII, +1/PDF page, ZDR +1 | Compute-unit based on run duration | Per browser-hour |
| **Method memory across requests** | **No** | **No** | **No** |

### 5.2 What is genuinely better for OUR server

1. **They cache *content*; we would cache *method knowledge*.** Firecrawl's `maxAge` is
   exactly the right idea applied to the wrong object. We keep the URL's content fresh while
   *also* knowing we can get it cheaply. Complementary, not competing.
2. **Cost-aware selection is impossible for them to do well.** Firecrawl charges per page
   regardless of method; internally they hide the cost of a Camoufox-equivalent. Pry owns
   its whole stack — proxy spend, browser-seconds, Tor, actor compute — so the
   `− w_c·norm_cost` term is a **real** decision, not a proxy for an internal chargeback.
   This is the single strongest differentiator.
3. **Locality of the wall.** Cloudflare/Pakuna walls are frequently **IP- and ASN-scoped**.
   Firecrawl's egress is shared across thousands of customers, so the method that works for
   their pool is not the method that works from Talos's IPs. Our memory is keyed to *our*
   egress, which is the only vantage point that matters for our scrapes.
4. **A 15-tier chain beats a session pool.** Apify's `SessionPool` assumes a proxy you can
   rotate. Pry's chain spans direct → TLS-fingerprint → cloudscraper → FlareSolverr →
   undetected → Camoufox → Playwright → Tor → premium proxy → archive → Google Cache →
   AI-vision → mobile-app API → GraphQL. When the answer is "this host has a public RSS feed"
   or "the mobile API is open", no competitor will find it, because they don't have tier 13-15.
5. **The method set is a *discovery* surface, not a fetch surface.** `hidden_api_discovery`,
   `sitemap_discovery`, `feed_parsing`, `graphql_discovery` are how you answer a target
   *without fighting its wall at all*. Competitors sell wall-clearing; we sell wall-avoidance
   as a first-class learned strategy.
6. **Self-hosted + x402 = a sellable primitive.** Method memory is a routing advantage on
   our own hardware, priced per-call over x402, with no third-party per-credit burn. That is
   a margin structure none of the three can match.
7. **Explainability as a product.** Tool #3 (`method_memory_explain`) returns *why* a scrape
   escalated, with per-attempt reasons and the rail that fired. None of the three exposes a
   comparable introspection surface — their escalation is a black box behind a credit
   counter. For an agent-driven buyer, that auditability is worth paying for.

### 5.3 Honest limitations — where they beat us

- **Cold start on a brand-new domain.** Our first attempt is the static 15-tier order; they
  have warm proxy reputation at the ASN level. Phase 4's Qdrant prior narrows this but does
  not close it.
- **Global proxy breadth.** Browserbase and Apify rent residential/ISP pools across
  continents. We have one Talos egress, a Tor circuit, and a paid proxy. A geo-blocked or
  reputationally-burned target will beat us until we buy more egress.
- **Operational load.** They absorb browser-patch rot, detection-fingerprint maintenance,
  and infra scaling. We absorb it too, on a 16-vCPU box that also runs Postgres, Redis,
  ClickHouse, Neo4j, Qdrant, Ghost, and n8n.
- **Flash-crowd targets.** A site that blocks us *today* may not block Firecrawl *today*. Our
  memory encodes a past truth; the explore window (§2.7) bounds the damage but doesn't
  eliminate it.

**Conclusion:** we are not competing on wall-clearing throughput. We compete on
*knowing, per domain, the cheapest thing that works from our own egress* — and being able to
explain that choice. That is a different product, and the three incumbents have no version of it.

---

## 6. Open questions

- **[REVIEW]** `engine/url_key.py` (49 lines) may already provide path-shape bucketing —
  confirm its contract before writing a new one.
- **[REVIEW]** `actor_factory/economics.py` exists; confirm whether it already prices
  actor compute-seconds, or whether `tier_cost.py` must define those independently.
- **[REVIEW]** `PryScraper` in `engine/scraper.py` is a *second*, older 10-tier chain
  alongside `UltimateScraper`'s 15. Both would need to feed one memory or the data splits.
  Confirm whether `PryScraper` is live or legacy before Phase 2 picks a single writer.
- **[REVIEW]** Multi-worker reality: is the API deployed with N>1 uvicorn workers? If so the
  in-process ring and `DomainTierMemory` are per-worker and PG/Redis become the real
  arbiter. This changes Phase 0's urgency framing.
- Cost figures for `premium_proxy` and actor methods are not in the engine today; Phase 1
  needs real numbers from `core/settings.py` before the `−w_c·cost` term can be calibrated.

## 7. Sources

- Local: `src/pry/engine/resilience.py`, `scraper_orchestrate.py`, `fallback_telemetry.py`,
  `block_detection.py`, `tiers_base.py`, `circuit_breaker.py`, `methods/registry.py`,
  `adaptive_selector.py`, `core/cache.py`, `core/db/models_scraping.py`,
  `api/routers/core/diagnostics.py`, `api/routers/commerce/x402.py`, `api/mcp_tools.py`,
  `pry_mcp/tool_registry.py`, `tests/test_resilience.py`
- External: `https://docs.firecrawl.dev/features/scrape` (formats, `maxAge`/`minAge`/
  `storeInCache`, credit table, enhanced mode)
- Corpus: `mendableai/firecrawl`, `apify/crawlee`, `unclecode/crawl4ai`
  (`MemoryAdaptiveDispatcher` — note: memory-pressure adaptive, *not* method memory),
  `internal/pryscraper`
