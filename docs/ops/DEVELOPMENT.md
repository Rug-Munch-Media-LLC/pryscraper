[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# DEVELOPMENT.md — PryScraper

> Dev workflow. Install, code, test, commit, PR.

## Setup

### Prerequisites
- Python 3.12+ / Node 20+
- A secrets manager (e.g. gopass, 1Password) for credentials
- `mise` for tool version mgmt (or manual)
- `pre-commit` for hooks

### Install
```bash
git clone &lt;your-repo-url&gt;
cd pryscraper
make install
pre-commit install
```

### Environment
```bash
# Required env vars (loaded from secrets manager on deploy, .env locally)
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
# Open a PR on your Forgejo/GitHub instance
```

### 6. Wait for CI
- All checks must pass
- Review by CODEOWNERS
- Squash-merge to main
- Auto-deploys via CI/CD webhook

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

Refer to your project's conventions document.


## Logging

Pry uses `structlog` for structured (JSON) logging per `CONVENTIONS.md` Part 5.
Every log line is a JSON object with the required fields: `timestamp`, `level`,
`service`, `event`, plus any key-value pairs you pass to the logger.

### Quick start

```python
from logging_config import setup_logging, get_logger

# Call once at process startup. api.py does this at module import time.
setup_logging()

log = get_logger(__name__)
log.info("scrape_started", url=url, mode="stealth")
log.warning("rate_limited", host=host, retry_after=retry)
log.error("scrape_failed", url=url, error=str(e))
```

Output (JSON, one record per line):

```json
{"url": "https://...", "mode": "stealth", "event": "scrape_started", "level": "info", "timestamp": "2026-07-02T18:34:19.567377Z", "service": "pry"}
```

### Configuration

Set via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_LOG_FORMAT` | `json` | `json` (production) or `console` (local dev, colored) |
| `PRY_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PRY_LOG_STRICT_EXTRAS` | (unset) | `1` to fail-fast on `extra={...}` keys that collide with reserved LogRecord names (default is lenient — reserved keys get moved to an `extra` sub-dict) |

### Backward compatibility

Code that uses stdlib `logging.getLogger(__name__)` keeps working. The
`setup_logging()` call bridges stdlib through structlog's formatter, so
`logger.warning("msg", extra={"foo": 1})` produces the same JSON shape as
`get_logger(__name__).warning("msg", foo=1)`.

### Reserved key gotcha

`logger.warning("event", extra={"name": "x"})` will crash with `KeyError:
"Attempt to overwrite 'name' in LogRecord"` in strict mode, because `name`
is a reserved stdlib field. In lenient mode (default) the key gets moved
to an `extra` sub-dict. **Prefer the structlog style** (`log.warning("event", name="x")`)
which doesn't have this issue.

### Where setup_logging() is called

- `api.py` at module import time (lifespan startup also calls it for safety)
- `cli.py` should call it before any logger usage (TODO)

### Adding to a new module

```python
from logging_config import get_logger  # or just `import logging; log = logging.getLogger(__name__)`
log = get_logger(__name__)

def my_function(x: int) -> int:
    log.info("my_function_called", x=x)
    return x * 2
```
