# ADR: Unlock Ledger — per-domain "how this site was unlocked" memory

Status: proposed · Date: 2026-10-25 · Supersedes: none

## Context

Pry already learns *how expensive* a domain is to reach: `domain_method_stats`
(one aggregate row per `(domain, method)` with attempts/wins/latency/cost) plus
`method_stats_store`'s non-blocking buffered writer, `_record_tier_outcome` in
`scraper_orchestrate`, and the tier-health ranking.

What it does **not** remember is the *recipe*: that `shops.example.com` needs a
`wait-for-selector` of `#grid` and one extra header, while its sibling needs the
JSON endpoint. Today that knowledge is re-derived on every run and dies with the
process. This ADR adds a small, separate ledger for the recipe — not chat
memory, not a prompt log.

## Decision

Add `UnlockLedger`: a SQLite sidecar holding one row per `(domain, method)`,
keyed on the **normalized host** (lowercase, scheme/path/port/`www.` stripped;
`shop.example.com` and `www.shop.example.com` are the same key). SQLite, not
Postgres, because unlock state must survive a database outage — the same reason
method stats degrade to in-process rather than raising.

### Record

| field | meaning |
|---|---|
| `domain` | normalized host (key, half 1) |
| `method` | `http` \| `api_endpoint` \| `headers` \| `wait_selector` \| `js_render` \| `proxy` \| `flaresolverr` (key, half 2) |
| `params` | JSON: endpoint, header **names**, selector, wait ms — secrets are redacted on write |
| `selector` | wait-for-selector / CSS path, empty when unused |
| `last_ok_at` | epoch seconds of last success, `NULL` if never |
| `ok_count` / `fail_count` | lifetime counters |
| `fail_streak` | consecutive failures since the last success |
| `latency_ms` | last observed latency |
| `notes` | free text, human-authored only |
| `approved` | 1 = a human blessed replay; 0 = discovered, replay-forbidden |

Counters are duplicated from `domain_method_stats` **on purpose** so the ledger
answers "which recipe" in one local query with no DB round trip. Wire-compatible
convergence into `domain_method_stats` is deliberately deferred: [REVIEW] a
follow-up should project `method_stats.wins/attempts` over the ledger rather
than let both drift. Until then `domain_method_stats` stays authoritative for
tier health, the ledger for recipe replay.

## Method selection

`choose_method(domain)` = **replay** path. Candidates are *approved* rows only,
ordered by:

1. freshness tier — recent success (`now - last_ok_at <= 24h`) and not stale → 0; not stale → 1; stale → 2;
2. then most lifetime wins (`-ok_count`);
3. then cheapest (`METHOD_COST`: http 0, api_endpoint 1, headers 2, wait_selector 3, js_render 4, proxy 5, flaresolverr 6);
4. then method name, so ordering is total and tests are deterministic.

No rows → fall back to `http` (zero behaviour change for unknown domains).

`repair(domain, attempt)` = **trial** path, used only after replay failed. It
walks `order_candidates` (approved rows, then the default ladder), calls
`attempt(method) -> (ok, latency_ms)`, records every outcome, and stops at the
first success. A winner that is not `approved` is returned with
`needs_approval=True` and is **not** replayed on the next run until a human
calls `approve(domain, method)`.

## Staleness

`STALE_AFTER_FAILURES = 3` consecutive failures. Stale rows sink to tier 2, so
the next-best candidate is tried before the rotted one. A single success resets
`fail_streak` to 0. A stale row is never deleted — `notes` and history are the
evidence a human needs to decide it truly rotted.

## Human approval — never auto-publish a bypass

`BASELINE_METHODS` (`http`, `api_endpoint`, `headers`, `wait_selector`) are
recorded `approved=1`: they are ordinary fetching knobs. `BYPASS_METHODS`
(`js_render`, `proxy`, `flaresolverr`) are recorded `approved=0` on discovery;
repair may *try* them but replay never uses them without `approve()`. The
ledger cannot promote its own bypass.

## Secrets

`params` is redacted before it touches disk: any key containing
`token|key|secret|password|passwd|auth|cookie|session|bearer|sig|credential`
stores `"<redacted>"`. Cookies, bearer tokens and API keys never enter the
ledger, and `repair` never invents one — it passes method *names* to the
caller's `attempt`, which owns credentials. A repair that would need a
credential the ledger does not have simply fails and is recorded as a failure.

## Same-family recall

`find_similar_domain(domain, known)` embeds domain names on the fleet
**Qwen3-Embedding-0.6B, 1024-d** lane (`PRY_EMBED_LANE_URL`, default
`http://127.0.0.1:8004`) and ranks by cosine; the 1024-d contract is enforced
(a dimension mismatch raises rather than silently scoring). The local reranker
orders only when the embed lane answers. **If the lane is unavailable the
result is `available=False` with the rule table used instead** — exact domain
plus registrable-host family (`host_family`). A down lane never fabricates a
vector, and a recall miss never blocks a repair.

## Honest limits

- **ToS / law.** A remembered method is a *fact about reachability*, not a
  licence. The ledger records what worked; it does not authorise circumventing
  access controls or a site's terms. Bypass methods stay behind human approval
  for exactly this reason.
- **A working method rots fast** — hours, not weeks. Selectors change on a
  deploy, a CDN flips, a challenge appears. Staleness after 3 failures is a
  heuristic, not proof the method is dead, and it can be wrong in both
  directions.
- **No credential invention.** The ledger stores no secrets and creates none.
  Auto-repair degrades to the methods it is handed.
- **Not wired into crawling yet.** `choose_method` returns `None` unless
  `PRY_UNLOCK_LEDGER=1`; that flag check is the single intended call site
  (`scraper_orchestrate` tier ordering). Nothing in the pipeline changes while
  it is off.
