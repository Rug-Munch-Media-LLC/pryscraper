# Mutation Testing Baseline — pryscraper

> Tool: mutmut 3.7.0 · Config: `[tool.mutmut]` in `pyproject.toml` · CI gate: `.forgejo/workflows/ci.yml` (mutation-score gate, blocking)

## Scope

Engine core (parsing/extraction/dedup/quality) — the code paths every scrape result
flows through:

| Source file | Lines |
|---|---|
| `src/pry/engine/parser.py` | 127 |
| `src/pry/engine/extraction.py` | 43 |
| `src/pry/engine/extractor.py` | 150 |
| `src/pry/engine/dedup.py` | 129 |
| `src/pry/engine/quality.py` | 402 |

Test selection: `tests/test_parser.py`, `tests/test_extractor.py`,
`tests/test_quality.py`, `tests/test_dedup.py`, `tests/test_dedup_mutation.py`,
`tests/test_quality_mutation.py`.

The sandbox needs the full package to resolve imports → `also_copy = ["src"]`
(mutmut writes the mutated engine files on top of the pristine copy).

## Measured baseline (2026-08-31, Talos, mutmut 3.7.0, --max-children 6)

```
killed:    746
survived:  303
timeout:     2
no_tests:  392
total:    1443
```

**Mutation score = killed / (total − no_tests − skipped) = 746 / 1051 = 71.0%**

CI gate baseline: **60%** (11 points of headroom below the measured baseline —
regressions fail the gate; noise does not).

## Rules

- Changes to the scope files that drop the score below 60% block merge.
- Raising the baseline: improve tests for the 303 surviving + 392 no-test mutants,
  then re-measure and bump BOTH the number here and `BASELINE` in `ci.yml`.
- The 392 no-test mutants are the highest-value target: they are lines the
  selected engine tests never execute.

## Regenerating

```bash
.venv/bin/mutmut run --max-children 6     # ~2 min on Talos
.venv/bin/mutmut export-cicd-stats        # → mutants/mutmut-cicd-stats.json
```
