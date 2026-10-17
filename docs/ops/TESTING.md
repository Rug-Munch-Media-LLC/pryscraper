# Testing

Pry runs one pytest suite. CI adds static gates around it. Every command below runs on Talos from the repo root.

## Run

```bash
pip install -e ".[dev]"        # pytest, pytest-cov, ruff, mypy, bandit
make test                      # pytest tests/ -v --cov=. --cov-report=term-missing
make check                     # lint + typecheck + test
make ci                        # precommit (ruff, mypy, bandit) + test
```

Focused runs:

```bash
pytest tests/test_15_tier_system.py -v
pytest tests/x402 -q
pytest -k "x402 and not integration" -q
```

Default selection comes from `[tool.pytest.ini_options]` in `pyproject.toml`: `-m 'not integration and not slow' --ignore=tests/contract`. Markers:

| Marker | Needs | Default |
|---|---|---|
| `integration` | live Postgres, Redis, external HTTP | skipped; run `pytest -m integration` |
| `slow` | long catalog/scan work | skipped; run nightly |
| `fuzz` | Hypothesis | separate job |

`tests/contract/` runs separately (`make test-contract`) because it starts a native Pact mock.

## What each gate enforces

CI: `.forgejo/workflows/ci.yml`.

| Gate | Command | Fails when |
|---|---|---|
| Lint | `ruff check . --exit-non-zero-on-fix` | any finding, or a fix was needed |
| Format | `ruff format --check .` | a file is unformatted |
| Types | `mypy src/ pry_mcp/ datasets/...` | a scoped package has a type error |
| Tests | `pytest tests/ --cov=pry --cov-fail-under=76` | a test fails, or coverage drops below 76% |
| Security | `bandit -r . -x ./tests/* -ll` | a medium+ finding |
| Secrets | `trufflehog git file://. --only-verified --fail` | a live credential in history |
| Structure | `scripts/check-structure.py` | a scanned file exceeds 500 lines |
| Monkeypatch | `scripts/check-monkeypatch.py` | the count rises above the baseline |
| Anti-patterns | `scripts/check-antipatterns.py` | any ratcheted rule regresses |

Ratchet gates only move down. `--update-baseline` may remove entries; adding one is the violation. The structure gate reports files over 150 lines as advisory and fails at 500.

## Coverage floor

76%. Defined twice, both must agree: `[tool.coverage.report] fail_under = 76` in `pyproject.toml`, and `--cov-fail-under=76` in CI. Codecov is informational only (`codecov.yml` sets `informational: true`).

`make test` uses `--cov=.` and does not apply the floor; CI uses `--cov=pry`. A green local run is not a coverage gate — run the CI command when you change coverage-sensitive code:

```bash
pytest tests/ --cov=pry --cov-report=term-missing --cov-fail-under=76 -m "not integration"
```

## Add a meaningful test

Test one behaviour, assert the value the caller receives.

Good — the request is unpaid, so the response is 402 and the quote names the price:

```python
def test_scrape_reports_price(client):
    resp = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp.status_code == 402
    accept = resp.json()["accepts"][0]
    assert accept["maxAmountRequired"] == "1000"  # $0.001 USDC, 6 decimals
    assert accept["network"] == "eip155:8453"
```

Why it works: it pins the contract (status, atomic amount, network) and would fail if pricing moved, decimals changed, or the gate disappeared.

Tautological — passes for any response, including a 500:

```python
def test_scrape(client):
    resp = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp is not None
    assert "data" in resp.text or True
```

It asserts the mock ran, not the behaviour. Delete it.

Rules for a new test:

1. Name the behaviour, not the function: `test_selfhost_serves_without_402`.
2. Assert exact values (`== "1000"`), not truthiness.
3. Use a real request path (FastAPI `TestClient`) where possible; mock only the network boundary.
4. Never use mainnet addresses or live keys. Fixtures live in `tests/fixtures_samples.py` and `tests/conftest.py`.
5. If the test needs Postgres or Redis, mark it `integration`.

## Before you push

```bash
ruff check . && ruff format --check .
pytest tests/ --cov=pry --cov-fail-under=76 -m "not integration"
python3 scripts/check-structure.py --repo .
python3 scripts/check-monkeypatch.py --repo .
python3 scripts/check-antipatterns.py --repo .
```
