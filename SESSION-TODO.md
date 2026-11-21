# SESSION-TODO — pryscraper — 2026-11-21

## State

`main` is at `4a6a6853`. Three PRs from this session are merged (#91, #94, #95).
The suite passes in CI (`test` green in 11m13s; it previously never completed).
The Docker image builds again and both containers run healthy, pinned to
`pryscraper:main-4a6a6853`.

The single most important thing this session established: **most of what looked
like flaky tests was a full disk.** `/tmp/pytest-of-root` had grown to 20GB over
27 sessions (8,949 directories per xdist worker from actor staging). That
saturated I/O (`wa=43%`, 74 processes in D-state, load1 630 on 64 cores), and the
host's CI kill-switch then correctly stopped the runners — so jobs were cancelled
before they could report, which read as "test keeps failing" with no log.

## Done (verified — with the command that proved it)

- [x] mega_search consensus — was inert because the fan-out exited at two *hits*
      rather than two *agreements*, so every result scored `consensus: 1`; the
      3.0s budget was also below five of six engines' latency.
      Proven live in the container: `mega_search('python asyncio tutorial')`
      → `engines_ok: ['searxng','mojeek']`, `consensus: [2,2,1,…]`, 11.2s under
      the 15s cap.
- [x] `create_all` 31.5s → 0.025s per test DB (SQLite `journal_mode=MEMORY`,
      `synchronous=OFF`, test-only, Postgres skipped by driver module).
- [x] `test_no_new_zero_importer_modules` — was walking 16,587 `.venv` files with
      an O(files × modules) membership test: 5 min CPU → 4.6s.
- [x] `-m "not integration"` silently re-enabled the `slow` tier by REPLACING
      `addopts`' expression; CI now spells out `not integration and not slow`.
- [x] `tmp_path_retention_policy="failed"` + `count=1` — 0 leftover session roots
      after a green run (measured).
- [x] Docker image unbuildable: `gen-docker-lock.py` used a hardcoded dev-tool
      block-list that omitted `semgrep`, colliding on `mcp==2.3.0`. It now
      projects the runtime closure from `uv.lock` (no extras/groups), so a dev
      tool cannot reach the image at all. `requirements.lock` regenerated from
      `uv.lock` too (was 104 packages stale).
- [x] `alembic`, `psycopg`, `asyncpg`, `psycopg2-binary` were declared dev-only
      but are runtime needs (entrypoint runs `alembic upgrade head`; production
      uses `postgresql://`). Deploying proved it: clean image restart-looped on
      `ModuleNotFoundError: No module named 'psycopg'`.
- [x] Shared-state leaks fixed at their owners: `settings.api_key` (monkeypatch
      ordering), global facilitator router replaced by a `TestRouter` and never
      restored, `url_terminal_state`, `tier_health.DEFAULT_PATH`, and tests that
      read the **production** `/root/.pry/pry.db` (now an autouse per-test DB).
- [x] pytest-timeout is a declared dev dependency, so the unit job can pass
      `--timeout=120`; previously a single stall consumed the whole job.
- [x] Closed stale PRs #92/#93 — forks from before the merges that would have
      reverted `mega_scoring.py` (-112 lines) and both lock files.
- [x] Session hygiene: 21 of 22 docker images and 28GB of pytest temp reclaimed
      (90% → 85% disk); my worktrees removed, `maines` snapshotted to
      `refs/backup/parked-req-lock-from-uv` first.

## Open (with the exact next command)

- [ ] **`main`'s `push` runs are red on 13 jobs**, but the set is unchanged from
      before this session and does not include `test`'s content. Check before
      touching: `docker exec -i rmi-postgres psql -U rmi -d forgejo -tAF'|' -c
      "select j.name,j.status from action_run_job j where j.run_id=(select max(id)
      from action_run where workflow_id='ci.yml')"`. Several are `slow`/nightly
      tiers that are advisory by design.
- [ ] **`/readyz` returns 503** with `{mode: self_hosted, wallet_configured:
      False}` while `/health` is 200 and the app serves. Pre-existing, not caused
      here. Next: decide whether the readiness gate should require a wallet in
      self-hosted mode — `docker exec pry python3 -c "from
      pry.payments.x402 import get_facilitator_router;
      print(get_facilitator_router().readiness())"`.
- [ ] **Host over-subscription**: 4 runners at 6 slots × `-n 2` on a box already
      running the production fleet. Seen 7 concurrent CI containers and load 212.
      This is `fleet-infra` territory (`/srv/ci/runner/*/config.y*ml` `capacity:`),
      deliberately NOT changed here.
- [ ] `pry-redis-exporter` is unhealthy (5+ days). Pre-existing, unrelated.

## Do not re-derive

- **A "flaky test" that only fails under parallelism is usually environment, not
  the test.** Check disk, D-state and load BEFORE bisecting tests. The 20GB
  pytest temp leak cost most of this session and presented as everything except
  what it was.
- **A CI job's comment does not describe its command.** The `test` job's comment
  described `-n auto` for weeks while the command passed no `-n` at all. Read the
  `run:` line.
- **`-m` on the CLI REPLACES `-m` in `addopts`; it does not intersect.**
- **Forgejo logs are readable**: `/data/gitea/data/actions_log/<owner>/<repo>/*/
  <task_id>.log.zst` inside `rmi-forgejo`; task id comes from
  `action_task WHERE job_id=<id>`. Zstd, no `zstd` binary in the container — copy
  out and decompress with the `zstandard` module. Do not conclude "logs are not
  exposed" from the 404s on the API.
- **`/srv/work/repos/pryscraper` is another lane's checkout** on
  `fix/ci-context-budget` with many dirty files. Never commit from it; work in a
  worktree off `origin/main`.
- **The deployed image must be tagged `main-<merge-sha>`** and both containers
  recreated with `PRY_IMAGE_TAG=... docker compose up -d --no-deps --pull never`;
  `latest` alone will not move a running container.
