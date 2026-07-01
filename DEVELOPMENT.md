# DEVELOPMENT.md — PryScraper

> Dev workflow. Install, code, test, commit, PR.

## Setup

### Prerequisites
- Python 3.12+ / Node 20+
- `gopass` for secrets
- `mise` for tool version mgmt (or manual)
- `pre-commit` for hooks

### Install
```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
make install
pre-commit install
```

### Environment
```bash
# Required env vars (loaded from gopass on deploy, .env locally)
# See .env.example
cp .env.example .env
$EDITOR .env  # fill in test values
```

## Workflow

### 1. Create a branch
```bash
git checkout -b feat/my-feature
# or fix/my-bug, docs/my-doc, chore/my-chore
```

### 2. Make changes
- Write code
- Add tests
- Update docs (AGENTS.md, ARCHITECTURE.md, STATUS.md)

### 3. Run pre-commit locally
```bash
make lint
make test
make typecheck
make security
```

### 4. Commit (conventional)
```bash
make commit   # interactive
# or:
git commit -m "feat(scope): add new feature"
```

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, ops, security

### 5. Push + PR
```bash
git push -u origin feat/my-feature
# Open PR on forgejo: https://git.rugmunch.io/RugMunchMedia/pryscraper/pulls/new
```

### 6. Wait for CI
- All checks must pass
- Review by CODEOWNERS
- Squash-merge to main
- Auto-deploys to Talos (via forgejo webhook)

## Daily End-of-Day
```bash
make status    # show what's changed
fleet-commit   # commit helper with checklist
```

## Code Style
- Python: ruff (lint + format), mypy strict
- TypeScript: eslint + prettier
- Shell: shellcheck
- Markdown: vale

See [standards/CONVENTIONS.md](https://git.rugmunch.io/RugMunchMedia/standards/raw/branch/main/CONVENTIONS.md).
