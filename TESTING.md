[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# TESTING.md — PryScraper

> Test strategy. Unit, integration, e2e, fixtures.

## Test Pyramid

```
       /\
      /  \      E2E (slow, few)
     /----\
    /      \    Integration (medium, more)
   /--------\
  /          \  Unit (fast, many)
 /____________\
```

- **Unit tests**: test individual functions/classes in isolation
- **Integration tests**: test components together (DB, API, auth)
- **E2E tests**: test full user flows (slow, run before deploy)

## Structure
```
tests/
├── unit/          # fast, no external deps
├── integration/   # uses test DB, mocks external APIs
├── e2e/           # full stack, runs against staging
├── fixtures/      # test data (mainnet guard: no real addresses/keys)
└── conftest.py    # pytest config
```

## Running

```bash
make test                  # all tests
make test-unit            # only unit
make test-integration     # only integration
make test-cov             # with coverage report
pytest tests/unit/test_X.py -v   # single file
```

## Fixtures

Use pytest fixtures. Examples:
- `clean_db` — fresh DB per test
- `mock_helius` — mock Helius API responses
- `auth_headers` — Bearer token for test user
- `sample_token` — fake token (test address, NOT mainnet)

**NEVER use mainnet data in tests.** Pre-commit hook blocks this.

## Coverage
- Target: >80% on changed lines
- Enforced in CI via `--cov-fail-under=80`

## Mocking
- `httpx` for HTTP mocking (use `respx` or `pytest-httpx`)
- `unittest.mock` for general mocking
- VCR.py for recording/replaying API calls

## Performance Tests
- `locust` for load testing (run against staging)
- Profile with `py-spy` or `cProfile`

## CI
Every PR runs:
1. Lint (ruff)
2. Type check (mypy strict)
3. Unit tests + coverage
4. Integration tests (test DB)
5. Security scan (bandit, gitleaks)
6. Build Docker image (verify it compiles)

Merge blocked if any fails.
