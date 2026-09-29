# PRY — next and needed

Written 2026-09-29. Read this before touching Pry, and re-verify everything
against the running container; a lot of this was learned the expensive way and
some of it is not what the code suggests.

Repo: `/srv/work/repos/pryscraper` · container `pry` on `127.0.0.1:8005` ·
health `{"status":"ok",...}` · auth mode `owner`.

---

## The one-line version

Pry works. It is a 12-tier anti-bot ladder with a paywalled default, and
almost all of the confusion so far came from three facts nobody had written
down: **the default timeout was shorter than the chain**, **the last tier in
the chain gets blamed for everything**, and **a `docker compose up` can re-trip
a fleet circuit breaker that parked a container**.

---

## 1. What is done and verified

| | commit | verified how |
|---|---|---|
| timeout default 30 → 120 | `9a67df85` | `ScrapeRequest().timeout == 120` in-container; 30s was shorter than a 12-tier × 45s chain, so requests died mid-chain and named whichever tier was in flight |
| auth mode self-declared | `2c9d3239`, `97de1577` | `pry_auth_mode=owner` in `docker logs`. Written to **stderr**, because the logger call in `kill_switches` was discarded — it is imported during app assembly, before `setup_logging()` runs |
| failure verdict | `e08be51d`, `1702a18c` | live: `verdict: blocked` + `tiers_attempted: 12` on a site that genuinely blocks |
| per-tier health (persistent) | `8524e2a0` | `direct 5 att 5 win 100% med 1280ms` read from the container |
| skip-on-zero-win | `fb1f9865` | 13 tiers instead of 14, `premium_proxy` gone, `direct` kept |
| backtest harness + baseline | `e08be51d`, `a606c8f3`, `66bc4f81` | `scripts/backtest_ladder.py`, `data/ladder_baseline.json` |
| premium_proxy promoted to rung 2 | `c235bfa9` | it was rung 10 of 12 and never reached |
| block detector: weak markers + size gate | `044e6e13`, `aa72ad7a`, `1b99b4b8` | a served page is no longer read as a block page |
| Webshare proxies wired | `56345b40` | 20 live; 3 verified presenting correct exit IPs and fetching the target with HTTP 200 from inside the container |

`0 unpushed` on `main` at last check.

---

## 2. Do these three things first

### 2a. Re-run the backtest twice, then judge the skip (blocking)

`should_skip()` requires 3 recorded attempts and zero wins ever. It is correct
that the deployed container reports `premium_proxy -> (False, 'no_evidence')`
until premium_proxy actually loses three times there — and it may never lose
again now that it is rung 2 and working. So the skip is now likely to be
**correctly dead code**: the tier it was written to disable has been fixed.

```bash
.venv/bin/python scripts/backtest_ladder.py --compare   # twice, warmed
docker exec pry python3 -c "
import sys; sys.path.insert(0,'/app')
from pry.engine.tier_health import report
print(report())"
```

Then answer one question honestly: **is premium_proxy now earning its cost?**
It wins the one source nothing else can reach, in ~2.5 ms, having previously
been unreachable. If yes, the skip is dead code and should stay as a safety
net for a regression. If it stops winning, the skip will fire on its own
evidence and you do not need to do anything.

### 2b. Retry / backoff — not started

There is no retry policy. One transient error still consumes the whole chain.
The per-tier cost is now recorded, so the input for this exists. Keep it
**bounded** and make the retry count visible in the response — an unbounded
retry is just a slower failure.

### 2c. Immunefi is flaky and will pollute your numbers

Three consecutive attempts returned three different tier signatures
(`undetected;camoufox;playwright`, `premium_proxy;tls_fingerprint`,
`googlebot;archive;google_cache`) for the same URL at the same reachability —
the late tiers are rate limited and intermittent. Direct HTTP is **3/3 at
~41 KB**. Use direct HTTP for that source; do not conclude Pry is broken when
it returns a different tier signature each time.

---

## 3. The ladder, and what each rung is actually worth

```
direct → tls_fingerprint → cloudscraper → flaresolverr → undetected →
camoufox → playwright → googlebot → tor → premium_proxy → archive → google_cache
```

**Final measured, 8 sources, warmed: 8/8, `direct` 5, `premium_proxy` 1,
`undetected` 1, `flaresolverr` 1, p50 3.7 ms, p95 5.1 ms.** Before this work
it was 5/8 at 0.625 with `direct` 4 and `flaresolverr` 1 and every other rung
on zero, while the three failures burned 25–45 s each — about 89 % of the wall
clock spent on rungs that never returned a result.

Each rung now has a measured job:
- **`direct` (5)** — free, ~3 ms, wins everything it is allowed to
- **`premium_proxy` (1)** — theblock.co, which 403s on plain curl. It was rung
  10 of 12 and never got reached; at position 2 it answers in 2.5 ms
- **`undetected` (1)** — slowmist.medium.com (403 to curl; its **RSS still
  returns 201 KB**, so curl remains the better path for that one)
- **`flaresolverr` (1)** — blog.soliditylang.com, which curl cannot reach at
  all (000). The browser pool is slow to start, so the harness warms it
  explicitly; without that it looks like a failure and skews latency 200x

- `flaresolverr` **does** earn its place — it recovered
  `blog.soliditylang.com`, which plain `curl` cannot reach at all (000).
- `premium_proxy` is wired with 20 verified-working proxies and has **never
  won a scrape**. A byte-exact replica of `_tier_premium_proxy` returns 200 with
  278,120 bytes. The proxies are fine; the rung is at the wrong end of the
  chain to be reachable before the budget runs out.

**Ladder for our sources: JSON API → RSS → curl + browser UA → Pry (last).**
From the sweep, 11 of 18 sources need nothing but curl. Slowmist is
Cloudflare-blocked as a page and its **RSS returns 201 KB** — the content Pry
cannot scrape is one feed away.

---

## 4. Traps that will cost you a session

**The circuit breaker will fight you.** Not an OOM, and this cost the most
time to find:

```
15:17:17 PARK pry-postgres: restarted 19x in 15m, 19 total
16:17:19 PARK pry-postgres: restarted 15x in 15m, 36 total
```

`docker-restart-circuit-breaker.sh:70` runs `docker stop -t 30`; the SIGKILL is
exit 137 and the unclean stop produces `database system was not properly shut
down; automatic recovery in progress`. **The loop is self-sustaining:** you
`compose up` to fix it, it restarts, the breaker re-parks it. Recovery:

```bash
grep -v '<container>' /run/docker-restart-cb.state > /tmp/cb && mv /tmp/cb /run/docker-restart-cb.state
docker compose -f docker-compose.yml up -d postgres
```

**A ghost container shadows a healthy one.** `docker compose up -d` failed with
"dependency failed to start: pry-flaresolverr is unhealthy" because a stale
`pry-flaresolverr` (restarting) shadowed the healthy `pry-flaresolverr-pry`.
`docker rm -f pry-flaresolverr` fixed it. If Pry will not start after a config
change, check for a duplicate before touching config.

**`/metrics` needs the ADMIN token, not the owner key** (owner gets 429), and it
is zeroed on every rebuild — that is why tier health is a file and not a metric
alone.

**The health file lives on the `pry-data` volume at `/app/pry-data`.** The
container is `read_only`, so that is the only writable path.

**`data/` is gitignored** and a bare `!data/file` negation cannot re-include a
file whose parent directory is excluded. Both the parent and the file must be
re-included. This silently produced an empty commit once.

**An async `timeout` parameter is a footgun.** Pry's budget is not an httpx
socket wait; the client param is named `pry_timeout`/`request_timeout`
specifically so the two cannot be confused. Sync file I/O inside an async
function needs `asyncio.to_thread`.

**Never `ruff --fix` a file you hand-edited without re-reading it.** It
reverted my ladder edit and I committed the result. The client file was
truncated to 21 lines in one commit — it is now guarded by a file-sanity check.

---

## 5. The method that worked, and the one that did not

**Working: measure the live thing, then re-measure.** Every real finding here
came from running a scrape and reading the output — never from reading the
code. The verdict field, the tier signature noise, the 30 s default, the
breaker, the ghost container, the gitignore trap and the truncated file were
all found by looking at what actually happened.

**Not working: trusting an error string to name its cause.** The chain's last
tier is `premium_proxy`, so every hard failure read as "the proxy is broken".
That sent two investigations into rotating Webshare credentials for a fault
that was a request budget. Generalise it:

> **When a layered system reports its last-resort component, that is evidence
> the earlier components were exhausted — not evidence the last one is broken.**

That is why `verdict` exists. Use it; do not infer from `detail`.

Same shape twice more: a stale Docker proxy shadowed a healthy one, and
`curl` reporting 404 for Immunefi was really Pry's chain timing out.

---

## 6. House rules that are not negotiable

- **Pry is the last rung.** API → RSS → curl+UA → Pry. Do not reach for it
  first; reaching for it first is how you end up scraping something that had an
  API.
- **One request ≈ one upstream fetch.** Bounded concurrency (2) and a 1 s gap.
  Pry idles at ~1.7 % CPU and 510 MB of 2 GiB, so capacity is not the
  constraint — being a good citizen to third-party sites is.
- **A green tick is not evidence.** Mutation-test anything that gates a
  decision. `should_skip` needs three independent conditions precisely so it
  cannot fire on a thin sample.
- **Never delete a collection or dataset** to make a run clean.
- **Assert against the live host.** Every claim here was verified; several
  earlier claims in this project's history were not, and they cost real time.

---

## 7. If you only have time for one thing

Run the backtest three times, watch the skip activate, and commit the
wall-clock delta. Everything else is polish; that is the number that tells you
whether the ladder is worth its depth — and right now 89 % of its time buys
nothing.
