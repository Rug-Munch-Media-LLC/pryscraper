# Pry — SLIs, SLOs and burn-rate policy

Owner: platform/backend. Sources of truth: `prometheus/alerts.yml` (rules),
`grafana/dashboards/pry-slo.json` (dashboard, uid `pry-slo`), this document (policy).
Operator steps live in `docs/ops/RUNBOOK-SLO.md`.

Every SLI below is computed from a metric that the app **actually emits**. If a
series is missing, the SLI is *unknown* — never "healthy". Check
`up{job="pry"}` before trusting a green panel.

## 1. SLIs and objectives

| # | SLI | Definition (PromQL) | Objective | Window | Source metric |
|---|-----|---------------------|-----------|--------|---------------|
| 1 | API availability | `1 - sum(rate(pry_requests_total{status=~"5.."}[W])) / sum(rate(pry_requests_total[W]))` | **99.5 %** | 30 d rolling | `pry_requests_total{method,endpoint,status}` |
| 2 | API latency (p95) | `histogram_quantile(0.95, sum by (le) (rate(pry_request_duration_seconds_bucket[W])))` | **p95 < 5 s** | 30 d | `pry_request_duration_seconds{endpoint}` |
| 3 | Scrape latency | `histogram_quantile(0.95, sum by (le) (rate(pry_scrape_duration_seconds_bucket[W])))` | **p95 < 10 s, p99 < 20 s** | 30 d | `pry_scrape_duration_seconds{method}` |
| 4 | Scrape success rate | `sum(rate(pry_scrapes_total{status="success"}[W])) / sum(rate(pry_scrapes_total[W]))` | **≥ 95 %** | 28 d | `pry_scrapes_total{method,status}` |
| 5 | Payment conversion | `sum(rate(x402_settle_success_total[W])) / sum(rate(x402_challenges_sent_total[W]))` | **≥ 20 %** | 28 d | `x402_challenges_sent_total`, `x402_settle_success_total` |
| 6 | Settlement success | `sum(rate(x402_settle_success_total[W])) / sum(rate(x402_settle_total[W]))` | **≥ 98 %** | 28 d | `x402_settle_total{network}`, `x402_settle_success_total{network}` |
| 7 | Monitor run success | `1 - sum(rate(pry_monitor_runs_total{status=~"error|timeout"}[W])) / sum(rate(pry_monitor_runs_total[W]))` | **≥ 95 %** | 7 d | `pry_monitor_runs_total{status}` |
| 8 | Queue lag | `pry_queue_oldest_job_age_seconds` and `pry_queue_depth` | **oldest < 5 min, depth < 100** | instantaneous + 10 m | `pry_queue_depth`, `pry_queue_oldest_job_age_seconds` (scrape-time collector) |
| 9 | Scheduler liveness | `time() - pry_scheduler_heartbeat` | **< 90 s** | continuous | `pry_scheduler_heartbeat` |

Notes:
- `/v1/scrape` latency is covered by SLI 3 (`pry_scrape_duration_seconds`), which
  is label-scoped by routing tier (`method`); request-level latency for the route
  is in SLI 2 under `endpoint="/v1/scrape"`.
- Conversion (SLI 5) is **not** an error budget in the availability sense: a
  legitimate drop in paid traffic can move it. It is alertable but never pages.
- Queue SLIs read the in-process queue only (`deps.queue._local_jobs`). A Redis
  outage that leaves the local LRU empty shows as *no series*, not zero.

## 2. Error budget

For an objective `O` over window `W`:

```
budget_fraction   = 1 - O                # 99.5% -> 0.005
budget_time       = (1 - O) * W          # 30d -> 3h 36m of allowed failure
burn_rate(t)      = error_ratio(t) / (1 - O)
budget_consumed   = ∫ burn_rate dt / W
```

Examples (availability, 30 d):
- `error_ratio = 7.2 %` → burn `14.4x` → whole 30 d budget in **50 h**.
- `error_ratio = 3.0 %` → burn `6x`  → whole budget in **5 d**.
- `error_ratio = 0.5 %` → burn `1x`  → budget exactly lasts the window.

Latency SLOs have no meaningful "budget fraction"; they use a **threshold +
sustained-window** policy (`p95 > 10 s` on both a long and a short window).

## 3. Multi-window burn-rate policy

Long window establishes the signal, short window proves it is still happening
(and makes the alert reset quickly). Both must be true.

| Burn | Long | Short | Severity | Action | Budget gone in |
|------|------|-------|----------|--------|----------------|
| 14.4x | 1 h | 5 m | **page** | rollback / failover now | ~2 d (30 d budget / 14.4) |
| 6x | 6 h | 30 m | **ticket** | fix same day | ~5 d |
| 1x | 3 d | 6 h | dashboard only | trend, no alert | 30 d |

Availability uses 14.4x/6x of `0.005` (i.e. 7.2 % / 3.0 % 5xx). Settlement
failure uses 14.4x/6x of `0.02` (28.8 % / 12 %). Conversion and latency use
explicit absolute thresholds because their "budget" is a product target, not an
error ratio.

**Paging vs ticketing**
- **Page** (`severity: critical`): availability fast burn, settlement fast burn,
  container/target down, public API probe failing, scheduler heartbeat stale,
  x402 gate misconfigured.
- **Ticket** (`severity: warning`): slow burns, single-tier scrape degradation,
  queue lag/backlog, p99 tail latency, monitor chronic failures, scraper idle.

## 4. Alert inventory (mapped)

| Alert | SLI | Severity |
|-------|-----|----------|
| PryAvailabilityBurnFast / PryAvailabilityBurnSlow | 1 | critical / warning |
| PryScrapeLatencyBurnFast / PryScrapeLatencyBurnSlow | 3 | critical / warning |
| PryScrapeLatencyP99High | 3 | warning |
| PryScrapeSuccessRateLow, PryScrapeMethodSuccessDegraded | 4 | warning |
| PryCheckoutConversionLowFast / PryCheckoutConversionLowSlow | 5 | critical / warning |
| PrySettlementFailureBurnFast / PrySettlementFailureBurnSlow | 6 | critical / warning |
| PryMonitorRunErrorRateHighFast / PryMonitorRunErrorRateHighSlow, PryMonitorNoSuccess12h | 7 | critical / warning |
| PryQueueLagHigh, PryQueueBacklog | 8 | warning |
| PrySchedulerHeartbeatStale | 9 | critical |
| pry_container_down, pry_public_api_down, pry_pg_down, pry_redis_down | availability preconditions | critical |
| PryRequestP95LatencyHigh | 2 | warning |
| PryPaymentGateMisconfigured | 5/6 precondition | critical |

## 5. Caveats (read before trusting a panel)

- **Histogram buckets are prometheus_client defaults** (`.005 … 10`). Values
  above 10 s are `+Inf`-bounded: a p95/p99 pinned at `10` means ">10 s", not
  exactly 10 s. Percentiles below 10 s are trustworthy.
- `pry_request_duration_seconds` labels `endpoint` with the matched route;
  unmatched paths are bucketed under `unmatched` (scanner noise visible, not
  mixed into real routes).
- `status` on `pry_requests_total` is the HTTP status string; `pry_scrapes_total`
  uses `success|error` and `method` is the routing tier, not a HTTP verb.
- Absent series ⇒ unknown. `absent()` is handled for heartbeat and target-down
  only; other rules simply cannot fire without data.
