<!--
SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
-->

# Contributing to Pry

> Multi-source crypto intelligence crawler. Production-grade FastAPI + Python 3.12.

## TL;DR

```bash
git checkout main && git pull --rebase upstream main
git checkout -b feat/my-change
# …make changes…
make lint test            # pre-push gate
make commit               # conventional commits via commitizen
git push upstream feat/my-change
# Open a PR on Forgejo (git.rugmunch.io/RugMunchMedia/pryscraper)
# After review: merge to main, push back to upstream
```

## Repository Model

This repo follows the **single-tenant branch-PR pattern** — a small team that
treats `feat/*` branches as the unit of review, merged directly to `main` after
CI passes and at least one approval.

### Branches

| Branch                | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `main`                | Production-ready. Protected. Forgejo-mirrored.   |
| `feat/<scope>`        | New feature or capability.                       |
| `fix/<scope>`         | Bug fix.                                         |
| `chore/<scope>`       | Tooling, deps, formatting, non-functional.       |
| `refactor/<scope>`    | Code restructure, no behavior change.            |
| `docs/<scope>`        | Documentation only.                              |
| `phase<N>-<scope>`    | Multi-commit initiative (e.g. `phase0-infra`).   |

### Commit Convention

We use **Conventional Commits** enforced by `commitizen` + `commitlint`.

```bash
make commit      # interactive — prompts for type, scope, message
```

Allowed types: `feat`, `fix`, `docs`, `refactor`, `style`, `test`, `chore`,
`ops`, `security`, `ci`, `build`, `perf`, `revert`.

Examples:
```
feat(api): expose /metrics endpoint as Prometheus text format
fix(pry): JWT fail-closed, fix gdpr_real SQL imports
docs(pry): add 2026-Q3 production audit + plan
ops(deploy): pin playwright>=1.50.0, add healthcheck stage
```

## Sync Workflow

### Daily sync

```bash
git checkout main
git pull --rebase upstream main      # rebase, never merge
git push upstream main               # fast-forward only
```

`pull.rebase=true` is set in `.git/config` — this is the default behavior.

### Working on a feature

```bash
git fetch upstream
git checkout -b feat/my-change upstream/main
# work, commit, repeat
git push upstream feat/my-change     # push branch to canonical
```

### After PR merged (or direct merge in single-tenant flow)

```bash
git checkout main
git pull --rebase upstream main      # picks up the merge
git branch -d feat/my-change         # delete local (use -D if not merged upstream)
```

## Remotes

| Remote          | URL                                         | Role                               |
|-----------------|----------------------------------------------|------------------------------------|
| `upstream`      | `git@git.rugmunch.io:RugMunchMedia/pryscraper.git` | **Canonical** — Forgejo.     |
| `origin`        | _(see forgejo)_                              | Fork/development use.              |

To add an external mirror (GitHub/GitLab/HuggingFace), add the remote under a
descriptive name (`github`, `gitlab`, `hf`).

## Pre-Push Checklist

Before pushing any branch:

```bash
make lint          # ruff check + format check
make typecheck     # mypy strict
make test          # pytest (see "Test Environment" below)
make security      # bandit + gitleaks (runs in CI; optional locally)
make ci            # all of the above
```

CI is defined in `.forgejo/workflows/ci.yml` and runs on every push.

## Test Environment

Some tests depend on external services:

| Service     | Required by                                        | How to run                |
|-------------|----------------------------------------------------|---------------------------|
| Postgres    | `tests/test_*_db*.py`, alembic migrations          | `docker compose up postgres` |
| Redis       | `tests/test_*_cache*.py`                           | `docker compose up redis` |
| FlareSolverr| `tests/test_anti_detection.py`                     | `docker compose up flaresolverr` |

Tests that require services will skip (or return 503 on `/ready`) without them.
This is expected — the production `/ready` endpoint is intentionally strict.

```bash
# Quick smoke (no services required)
PRY_JWT_SECRET=test-secret pytest tests/test_x402_mcp_spec.py tests/test_api_surface_snapshot.py tests/test_compliance.py -q
```

## Disaster Recovery

Before any risky operation (`reset --hard`, `rebase`, large `cherry-pick`):

```bash
git bundle create /tmp/pry-backup-$(date +%Y%m%d-%H%M%S).bundle --all
```

To restore from a bundle:

```bash
git clone /tmp/pry-backup-XXX.bundle /tmp/pry-restored
```

The bundle includes **every ref** — branches, tags, stashes-as-commits,
remote-tracking branches. To restore just `main`:

```bash
git clone -b main /tmp/pry-backup-XXX.bundle /tmp/pry-restored
```

## Working with Archived Work

Phase-0 work (the 5 commits originally on `feat/metrics-endpoint` local-only)
was preserved during the 2026-Q3 reorg and **cherry-picked onto `main` on
2026-07-06**:

| Original commit | Patch | Status on `main` |
|-----------------|-------|------------------|
| `47875ae` JWT fail-closed + gdpr_real SQL imports + Ollama URL | `0001-…patch` | **Subsumed** — canonical `auth.py` already fail-closes via `secrets_backend.get_secret()` |
| `6cf0122` 10-tier → 5-tier + delete `browser_pool.py` + `stealth_engine.py` | `0002-…patch` | **Skipped (conflicts)** — canonical `feat/wire-orphan-modules` wired both modules into the fallback chain; deletion would break `scraper.py`/`cookie_warmer.py` imports |
| `68a51c2` kill cli recursion + delete `parser.tmp` + fix completions + correct hallucinated docs | `0003-…patch` | **Cherry-picked** (2026-07-06) |
| `7c3d5b7` add missing deps (cloudscraper, aiohttp-socks, pyjwt, apify, playwright-stealth) + docker fixes | `0004-…patch` | **Cherry-picked** (2026-07-06) |
| `1698a47` respx + coverage gate + commitizen make target + `.github/workflows/ci.yml` updates | `0005-…patch` | **Skipped (wrong target)** — canonical CI lives in `.forgejo/workflows/ci.yml`, not `.github/`. The Makefile already runs `pytest … --cov=.`; respx test stub landed separately via `chore(mcp,x402): add API-surface snapshot tests before file split` |

Patches remain in `/tmp/pry-phase0-patches/` for reference and can be
re-applied with `git am` on a fresh branch if any of the skipped commits need
to be revisited (e.g. if `feat/wire-orphan-modules` is later reverted).

The `phase0-fixes-archive` branch tip (`47875ae`) and `pre-phase0-wip-archive`
branch are kept for archaeology — do not delete without backing up first.

For the full Phase 0+ plan see [`AUDIT-2026-Q3.md`](AUDIT-2026-Q3.md).

## License

Dual-licensed:

- **MIT** for core modules (any PR welcome).
- **BSL 1.1** for stealth/anti-detection code (listed in `LICENSE-BSL-STEALTH`).
  Only Rug Munch Media LLC can modify BSL files. PRs that touch BSL files will
  be rejected.

When contributing, you agree your MIT-licensed contributions may be relicensed
by Rug Munch Media LLC under compatible terms.

## Code of Conduct

Be precise, be kind. Cite file:line when reviewing. Prefer surgical commits
over sweeping refactors.

## Further Reading

- `AGENTS.md` — repo contract, owners, commands, dependencies
- `ARCHITECTURE.md` — module layout, data flow, deployment
- `STATUS.md` — current sprint status (update before each commit)
- `PLAN.md` — roadmap and active initiatives
- `AUDIT-2026-Q3.md` — production readiness gap analysis
- `../standards/CONVENTIONS.md` — fleet-wide conventions
- `../standards/TOOLCHAIN.md` — tool inventory