# SESSION-TODO — pryscraper — 2026-11-21

## State

`main` is at `a25e7f09`. Seven PRs from this session are merged in pryscraper
(#91, #94, #95, #98, #100) and three in fleet-infra (#476, #479, #485, #487, #488).

**The suite runs green**: `pytest tests/ -n 4 --dist loadfile` → 9,760 passed in
4m53s locally. In CI, `lint` (218s) and `typecheck` (172s) both pass now — they
failed on every run for the whole session and were fixed here.

The single most important thing this session established: **most of what looked
like flaky tests was infrastructure.** Four separate faults, in order of damage:

1. **The queue reaper cancelled every `main` run** — `branch_head()` passed the
   full ref (`refs/heads/main`) to an API that wants the short name, got a 404,
   read it as `__gone__` = "superseded", and cancelled. 211 runs. Fixed + 6 tests.
2. **A `.venv` symlink was committed** (by my own `git add -A` in 4488a8af), so
   checkout wrote a FILE where `uv venv` needed a DIRECTORY: every job died in
   42s. Removed; `.gitignore` had `.venv/` (trailing slash ignores only dirs).
3. **The runner pool was inverted**: 6 "slots" over four 2-core cpusets meant two
   jobs sharing two cores — 1 core each. Now 4 slots x 2 cores x 4GB.
4. **`runner.timeout: 20m` was below the workflows' own 30m budget**, so jobs
   were reaped, not failed. Now 35m.

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

- [ ] **7 jobs still fail on `main`'s push runs** — all fast (25-261s), none of
      them `test`: `Code complexity`, `Mutation testing`, `Secret scan`,
      `k6-smoke`, `pre-commit-mirror`, `supply-chain`, `wheel-smoke`. They are the
      jobs PR #98 moved off the PR path; they still run on main by design.
      Next: the CI job table in the forge database — select job names where the newest
      `ci.yml` run's job status is failed.
- [ ] **`fleet-gates` can now be made a required check.** It passes on
      fleet-infra main for the first time (PR #488, 5 ok / 0 fail), which was the
      blocker. Next: add `CI / fleet-gates (pull_request)` to
      `status_check_contexts` in that repo's branch protection — a red gate that
      cannot block is the "decoration" GATING.md warns about.
- [ ] **`vulture` flags `scan()` in scripts/antipattern_rules.py as unused**
      (60% confidence). It is used — imported dynamically by
      check-antipatterns.py:110. A false positive, recorded so nobody "fixes" it.
- [ ] **`/readyz` returns 503** with `{mode: self_hosted, wallet_configured:
      False}` while `/health` is 200 and the app serves. Pre-existing, not caused
      here. Next: decide whether the readiness gate should require a wallet in
      self-hosted mode — inspect the readiness value in the running container, from
      pry.payments.x402 import get_facilitator_router;
      print(get_facilitator_router().readiness())"`.
- [ ] **Host over-subscription**: 4 runners at 6 slots × `-n 2` on a box already
      running the production fleet. Seen 7 concurrent CI containers and load 212.
      This is `fleet-infra` territory (the runner pool config's `capacity:` key),
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
  <task_id>.log.zst` inside the forge container; task id comes from
  `action_task WHERE job_id=<id>`. Zstd, no `zstd` binary in the container — copy
  out and decompress with the `zstandard` module. Do not conclude "logs are not
  exposed" from the 404s on the API.
- **The shared `pryscraper` checkout is another lane's** on
  `fix/ci-context-budget` with many dirty files. Never commit from it; work in a
  worktree off `origin/main`.
- **The deployed image must be tagged `main-<merge-sha>`** and both containers
  recreated with `PRY_IMAGE_TAG=... docker compose up -d --no-deps --pull never`;
  `latest` alone will not move a running container.
