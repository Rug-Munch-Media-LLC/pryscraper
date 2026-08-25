# Pry Incident Runbook

> One page. Three flows. On-call ready.
> Owner: Rug Munch Media LLC Engineering · Updated 2026-08-25

## Severity Ladder

| Sev | Trigger | Response |
|-----|---------|----------|
| S1 | Public API down (`api.pryscraper.com` failing) or paid path leaking free | Page now, all hands |
| S2 | Degraded (scrape failures spike, queue backlog, one dependency down) | On-call within 30 min |
| S3 | Actor build failures, single data-domain drift | Next business hours |

Detection: Gatus (`pry-api`, `pry-public-api` endpoints) → Telegram.
Prometheus targets on `pry-prometheus` :9090 (6/6 must be UP).

---

## Flow 1 — Apify Actor Build Failing

**Symptom**: Apify build page red, or CI `apify-actor.yml` build job red.

1. Read the build log on the Apify console (or Forgejo job log) — 90% are
   `requirements.lock` resolution failures or a Dockerfile base-image change.
2. Reproduce locally:
   ```bash
   python -m actor_factory.cli stage pry-cve-advisory-watch /tmp/stage
   docker build -f .actor/Dockerfile.apify /tmp/stage/pry-cve-advisory-watch
   ```
3. If a dependency broke upstream: pin the offending package in
   `_actor_lock_contents` source (`requirements.lock`) and regenerate locks
   via `scripts/gen-docker-lock.py`.
4. If the base image moved: pin by digest in `.actor/Dockerfile.apify`
   (`apify/actor-python-playwright@sha256:...`) — never float `latest`.
5. Publish is dispatch-locked (never fires on push). After green, publish
   manually per the workflow's arm instructions.

**Never** bump the catalog version to re-run builds — version bumps are for
Store launches only (recipe-miner carries 26 debug builds under 1.0).

## Flow 2 — Upstream Platform API Change

**Symptom**: one data-domain actor/router returns structured empties or
schema errors; live-fire verification fails for a single family.

1. Confirm scope: run the family's router smoke test
   (`pytest tests/test_routers_<domain>.py -q`). One domain = upstream
   drift; many domains = our deploy (check last image rebuild).
2. Diff the upstream response shape against the parser:
   ```bash
   curl -s '<upstream-endpoint>' | jq 'keys'
   ```
3. Fix the parser additively (accept old + new shape) — never break the old
   shape in the same release that adds the new one.
4. Update the family README "Last verified" line + date after live-fire
   passes (trust signal, auto-updated by the verification script).
5. If upstream is hard-down (API retired): gate the router behind a
   capability flag and mark the actor `PAUSED` on the Store — do not ship
   an actor that returns fabricated empties.

## Flow 3 — Abuse Storm (scrape-farm / key-stuffing)

**Symptom**: request rate from few IPs spikes; rate-limit-blocked log lines
surge; metering shows one key burning quota.

1. Confirm in Prometheus: `pry_requests_total` by IP bucket, 429 rate.
2. Kill switch at the edge first, investigate second:
   ```bash
   # nginx: deny the offender subnet
   # /etc/nginx/sites-available/api.pryscraper.com → deny <cidr>;
   nginx -t && systemctl reload nginx
   ```
3. Revoke abusive keys immediately (remote admin):
   ```bash
   curl -X DELETE https://api.pryscraper.com/v1/keys/<key_id> \
        -H "Authorization: Bearer $(gopass show -o pry/ops_admin_key)"
   ```
4. If x402 payments are being replayed: check the nonce store
   (`payments[payment_id]` expiry map) and rotate `PRY_WEBHOOK_SECRET` if
   webhook forgery is suspected (gopass `pry/webhook_secret`, restart pry).
5. Persistent abuse → enable Cloudflare bot-fight mode for the zone
   (DockFlare dashboard) as a temporary shield while tuning limits.

---

## Escalation & References

- Deploy: `docker compose build pry && docker compose up -d pry` (Talos)
- Key management: gopass `pry/ops_admin_key`, `pry/webhook_secret`,
  `rmi/forgejo/api_token` (branch unlock/relock)
- Monitoring: Gatus dashboard, Prometheus :9090, Grafana (pry-grafana)
- Post-incident: file the retro in `/root/.knowledge/verification_log.txt`
  with timeline + root cause + gate that should have caught it.
