# Compose service hygiene

Two rules, both learned the hard way on 2026-09-29.

---

## 1. A declared service vs a true orphan

A container that is running is **not** evidence that anything wants it. Compose
leaves orphans behind constantly — a `docker compose down`, a `docker rm`, a
profile change, a hand-edit of the YAML — and the result is a running container
serving requests with no declaration behind it. Nothing in the logs
distinguishes the two cases. The name does not either.

### The one-command test

```bash
docker rm -f <container>
docker compose up -d
docker compose ps <service>
```

- **It comes back** (seconds — a declared service with a healthy image) →
  it was declared all along. Not an orphan.
- **It does not come back** → it was an orphan. Safe to delete the container
  and forget it.

That is the whole check. It is cheaper and more reliable than reading logs,
checking uptime, or reasoning about how long a process "should" have been
running.

### The mistake this replaced

`pry-flaresolverr` was called a "ghost" — a stale orphan silently serving old
requests — on the strength of its name and a 7-hour uptime, and the claim was
written into permanent memory as fact. It was false. Both FlareSolverr
containers are declared services, `flaresolverr-pry` and `flaresolverr`. The
test that proved it took one command: removed, `docker compose up -d`, back 44
seconds later.

Uptime means nothing. `restart: unless-stopped` means a container has been up
since the last host reboot regardless of whether any consumer still calls it.
**A real service comes back; an orphan does not.** Run the test before writing
any claim about a container into memory.

---

## 2. The env value and the `depends_on` must name the SAME service

A service can be named in two places, and they drift apart silently. Both were
wrong in different directions for as long as they disagreed.

Fixed in `53381ae6`:

| What | Before | After |
|---|---|---|
| `PRY_FLARESOLVERR_URL` (the call) | `flaresolverr-pry` | `flaresolverr-pry` |
| `depends_on` (the wait) | `flaresolverr` | `flaresolverr-pry` |

The failure mode is quiet and one-directional. Pry called one instance and
waited on the health of the *other*, so:

- Pry's readiness was gated on a service it never called.
- That service was the *shared* one, which degenfeed saturates (queue 40+) —
  so a busy neighbour could block or delay Pry's own start.
- Nothing errored. The health check genuinely passed. It was just passing for
  the wrong service.

### The rule

For any dependency, these must all name the same service:

1. the **env var** holding its URL or hostname,
2. the **`depends_on`** entry that gates startup on its health,
3. any **monitoring target** that probes it (Prometheus blackbox, gatus).

When you add or rename a dependency, change all three together. They sit a few
lines apart in the same service block, which is exactly why they drift.

---

## One FlareSolverr, one name

Retired 2026-10-26 (`7224611d`): there used to be two instances, `flaresolverr`
and a per-app `flaresolverr-pry`, and Pry **called one while waiting on the
other**. T1 then dialled `flaresolverr-pry`, which was not running, and failed
at DNS on every call.

The single truth now:

| | value |
|---|---|
| URL (`PRY_FLARESOLVERR_URL`, `settings.flaresolverr_url`) | `http://flaresolverr:8191/v1` |
| Owner | `fleet-infra/compose/flaresolverr.yml` — one container, published on `127.0.0.1:8192` |
| How Pry reaches it | that container joins `pryscraper_default` under the alias `flaresolverr` |
| `depends_on` | **no entry** — the solver is not a pryscraper service, so compose cannot gate on it; `/health` probes it instead |
| `docker-compose.selfhost.yml` | bundles its own solver and gives it the **alias** `flaresolverr`, so the same URL works with no fleet |

The gatus probe (`fleet-infra/compose/gatus/gatus.yml` →
`http://127.0.0.1:8192/health`) still targets the published port from outside
this repo. Never reintroduce a second name: config, code default and
`depends_on` must all read `flaresolverr`.

> `[REVIEW]` The gatus container is **not currently running** on this host
> (`docker ps -a` shows no `gatus`), and no established TCP connection to 8192
> was observed. The declaration is the evidence that the port is a real
> published interface, not proof of live traffic today. Treat the shared
> service as load-bearing until someone confirms the probe is retired —
> it is one line to remove once the consumer is gone, versus an outage if
> removed early.

The self-host overlay already removes it by design. Deleting it from the base
file would also break that overlay's explicit `!reset null` entry, which
assumes the service exists to be removed.
