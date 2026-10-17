# RUNBOOK — Pry SLO & reliability alerts

Source of truth: `prometheus/alerts.yml`. Dashboard: `grafana/dashboards/pry-slo.json`
(uid `pry-slo`). SLOs: availability 99.5%, scrape p95 < 10s, 402→settle ≥ 20%,
settlement failure ≤ 2%, monitor run success ≥ 95%. Fast window 1h, slow 6h.
Every alert states the metric it reads; if a metric is absent, the rule cannot fire
(Prometheus returns no series) — check `up{job="pry"}` first.

## PryAvailabilityBurnFast
**Means:** >7.2% of API requests are 5xx across 1h and 5m — burning the 99.5% budget at >14.4x.
**Checks:** 1) `curl -s localhost:8002/health` 2) `curl -s localhost:9090/api/v1/query --data-urlencode 'query=sum by (endpoint)(rate(pry_requests_total{status=~"5.."}[5m]))'` 3) recent deploy/restart in logs.
**Mitigate:** roll back the last deploy; restart the API container; if one upstream provider is failing, disable that provider route.
**Escalate:** page the on-call backend engineer immediately; open an incident if >15m.

## PryAvailabilityBurnSlow
**Means:** sustained >3% 5xx over 6h and 30m — slow budget erosion, not a blip.
**Checks:** 1) top failing endpoint (query above) 2) error types in logs 3) dependency health (`pry_pg_down`, `pry_redis_down`).
**Mitigate:** fix or disable the failing endpoint/provider; scale the API if saturation.
**Escalate:** ticket to backend owner same day; page if it becomes fast burn.

## PryScrapeLatencyBurnFast
**Means:** scrape p95 > 10s across 1h and 5m — the scrape SLO is breached.
**Checks:** 1) `histogram_quantile(0.95, sum by (le, method)(rate(pry_scrape_duration_seconds_bucket[5m])))` 2) proxy/browser pool health in `/v1/admin/dashboard` 3) FlareSolverr probe (`up{job="flaresolverr"}`).
**Mitigate:** drain/restart the slow tier; rotate proxy pool; reduce concurrency to avoid queueing.
**Escalate:** page on-call if it persists 15m; notify the scraping owner.

## PryScrapeLatencyBurnSlow
**Means:** p95 > 10s over 6h and 30m — latency drift, often one method.
**Checks:** 1) p95 by method 2) per-method success rate 3) upstream response times in logs.
**Mitigate:** move traffic off the degraded method; refresh proxy/browser sessions.
**Escalate:** ticket to scraping owner with the slow method identified.

## PryCheckoutConversionLowFast
**Means:** <10% of 402 challenges settle over 1h and 5m (half the 20% objective).
**Checks:** 1) `x402_verify_failure_total` by `reason` 2) `x402_facilitator_health` 3) recent pricing/gate change.
**Mitigate:** restore the failing facilitator/chain; revert a bad pricing or PAYMENT-REQUIRED change.
**Escalate:** page payments owner — revenue path is degraded.

## PryCheckoutConversionLowSlow
**Means:** conversion <15% over 6h and 30m — client mix or chain support drift.
**Checks:** 1) conversion by `network` 2) challenge volume by `operation` 3) client errors after 402.
**Mitigate:** re-enable a disabled chain/asset; correct pricing so clients can pay.
**Escalate:** payments owner ticket; include the network split.

## PrySettlementFailureBurnFast
**Means:** >28.8% of settlement attempts fail over 1h and 5m (2% SLO, 14.4x burn).
**Checks:** 1) `x402_replay_detected_total` rate 2) `x402_rpc_latency_seconds` p95 3) facilitator logs / balance.
**Mitigate:** fail over to a healthy facilitator/RPC; top up gas; stop replaying a poisoned tx.
**Escalate:** page payments on-call; treat replays as potential fraud.

## PrySettlementFailureBurnSlow
**Means:** >12% settlement failures over 6h and 30m.
**Checks:** 1) failure ratio by `network` 2) RPC latency trend 3) facilitator health history.
**Mitigate:** shift traffic to a healthy chain RPC; retry backlog after recovery.
**Escalate:** payments owner ticket; escalate if ratio keeps climbing.

## PrySchedulerHeartbeatStale
**Means:** `pry_scheduler_heartbeat` older than 90s (3× the 30s interval), or absent while the target is up.
**Checks:** 1) `PRY_SCHEDULER_ENABLED` env 2) logs for `scheduler_tick_failed` 3) `pry_monitor_runs_total` rate.
**Mitigate:** re-enable the scheduler and restart the API; if a tick hangs, restart to clear the loop.
**Escalate:** page on-call — monitors stop silently without this loop.

## PryMonitorRunErrorRateHighFast
**Means:** >30% of monitor runs are error/timeout over 1h and 5m (95% success SLO).
**Checks:** 1) `pry_monitor_runs_total` by status 2) per-monitor error logs 3) target site availability.
**Mitigate:** raise `PRY_SCHEDULER_CONCURRENCY` only if timeouts (not errors); disable a dead target's monitor.
**Escalate:** page on-call if monitors are customer-facing.

## PryMonitorRunErrorRateHighSlow
**Means:** >15% failures over 6h and 30m — chronic.
**Checks:** 1) failing monitors list 2) error messages 3) recent detector changes.
**Mitigate:** fix the extractor/selector or mark the monitor inactive; retry backoff is `PRY_MONITOR_RETRY_BACKOFF_S`.
**Escalate:** ticket to monitoring owner.

## PryMonitorNoSuccess12h
**Means:** no monitor has recorded success in 12h while runs continue (global — schedules live in the DB, not metrics).
**Checks:** 1) `max(pry_monitor_last_success_timestamp)` age 2) run status split 3) whether all active monitors are failing.
**Mitigate:** fix the common failure (target down, auth, parser); trigger one monitor manually via `/v1/monitor`.
**Escalate:** on-call if customer monitors are affected.

## PryScrapeMethodSuccessDegraded
**Means:** one `method` tier is below 70% success while it still has volume. There is no `tier` label — `method` is the exposed routing dimension.
**Checks:** 1) success ratio by `method` 2) that method's proxy/browser pool 3) error strings for that tier.
**Mitigate:** remove the bad proxy/browser nodes; route traffic to a healthy method.
**Escalate:** scraping owner ticket with the failing method name.

## PryScrapeSuccessRateLow
**Means:** overall scrape success < 90% for 15m while scrapes are running.
**Checks:** 1) per-method split 2) upstream block rate (403/429) 3) proxy pool size.
**Mitigate:** rotate proxies; reduce request rate; switch to browser method for blocked targets.
**Escalate:** scraping owner; page if it persists past 1h.

## PryScraperIdle
**Means:** zero scrapes for 2h while the API target is up — nothing is being collected.
**Checks:** 1) `rate(pry_scrapes_total[15m])` 2) queue depth / worker logs 3) scheduler heartbeat.
**Mitigate:** restart workers; confirm the job queue is consuming; re-enable scheduling.
**Escalate:** on-call — silent data loss.

## PryRequestP95LatencyHigh
**Means:** API p95 request duration > 5s for 20m (envelope latency, not scrape time).
**Checks:** 1) p95 by `endpoint` 2) DB/Redis latency 3) event-loop blocking in logs.
**Mitigate:** scale workers; add a timeout to the slow endpoint; shed load.
**Escalate:** backend owner if user-facing.

## PryPaymentGateMisconfigured
**Means:** a paid endpoint prefix has no `X402_PRICING` entry; requests fail closed with 500.
**Checks:** 1) `increase(pry_x402_gate_misconfigured_total[5m])` 2) logs `x402_gate_misconfigured` (`operation`, `path`) 3) diff `PAID_ENDPOINTS` vs `X402_PRICING`.
**Mitigate:** add the missing price or remove the prefix; redeploy config.
**Escalate:** page payments owner — revenue is being refused.

## pry_container_down
**Means:** Prometheus cannot scrape `pry:8002` for 2m.
**Checks:** 1) `docker ps` for the API container 2) container logs 3) host disk/memory.
**Mitigate:** restart the container; roll back the last image if it crash-loops.
**Escalate:** page on-call immediately.

## pry_high_error_rate
**Means:** 5xx ratio > 10% over 5m (symptom-level companion to the burn alerts).
**Checks:** 1) top 5xx endpoint 2) traceback in logs 3) dependency `up` metrics.
**Mitigate:** roll back, restart, or disable the failing dependency path.
**Escalate:** page on-call if it lasts 10m.

## pry_pg_down
**Means:** postgres exporter unreachable for 2m — DB or exporter down.
**Checks:** 1) `docker ps` for postgres/exporter 2) `pg_isready` 3) disk space.
**Mitigate:** restart the exporter first; then the DB if unresponsive.
**Escalate:** page DB owner; data-loss risk if the DB itself is down.

## pry_redis_down
**Means:** redis exporter unreachable for 2m — cache/queue at risk.
**Checks:** 1) container status 2) `redis-cli ping` 3) memory/eviction logs.
**Mitigate:** restart Redis; if evicting, raise memory or reduce cache TTLs.
**Escalate:** page on-call — job queue and rate limiting degrade.

## pry_public_api_down
**Means:** the external blackbox probe of `https://api.pryscraper.com/health` fails for 2m.
**Checks:** 1) internal `up{job="pry"}` 2) Cloudflare tunnel status 3) nginx/proxy logs.
**Mitigate:** restart the tunnel/nginx; fix DNS or certificate; fail over to the direct origin.
**Escalate:** page on-call — customers see an outage.
