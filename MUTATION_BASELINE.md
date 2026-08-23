# Mutation Testing Baseline — pryscraper

**Tool:** mutmut 3.7.0 · **Scope:** core parsing/extraction modules · **Recorded:** 2026-08-22

## Baseline: 36.7%

| Metric | Value |
|---|---|
| Mutants generated | 1,443 |
| Killed | 308 → **436** |
| Survived | 531 → ~433 |
| No tests | 604 → ~167 |
| **Score (covered)** | **36.7% → 43.3%** (dedup.py suite added) |

### Scope
`parser.py` (127) · `extraction.py` (43) · `extractor.py` (150) · `dedup.py` (129) · `quality.py` (402)

### Reading
- ~~604 no-test mutants: dedup.py had no dedicated test file~~ ✅ CLOSED: tests/test_dedup.py (22 cases: SimHash determinism/empty-input, hamming exact values, similarity formula, cluster grouping, diff severity ordering)
- 531 survivors across parser/extractor/quality: boundary conditions in scoring
  weights and parse edge cases are the likely clusters (same pattern as rmi-alpha)
- Gate: no >5pt regression; target ≥80% on covered set

## Config (pyproject.toml)

```toml
[tool.mutmut]
source_paths = ["parser.py", "extraction.py", "extractor.py", "dedup.py", "quality.py"]
pytest_add_cli_args_test_selection = ["tests/test_parser.py", "tests/test_extractor.py",
  "tests/test_quality.py", "tests/test_pry_mcp_quality.py",
  "--deselect", "tests/test_pry_mcp_quality.py::TestRegistryConsistency"]
```

### Sandbox notes
- Flat layout imports (`from parser import ...`) work as-is — no src.* trap here
- `TestRegistryConsistency` deselected: reads root JSON registries absent from the
  sandbox; zero mutation value for the scoped modules
- mutmut 3.7.0 (newer than other repos — config keys compatible)

## Update log

### 2026-08-23 - dedup.py driven to equivalence-limited (audit win #6)
- Survivors: 39 -> **4**, all four PROVEN equivalent:
  - `hash__mutmut_1` (n_features default 128->129): md5 hexdigests are exactly
    128 bits, so feature bit 128 never receives a vote - output identical.
  - `hash__mutmut_20/22/23` (usedforsecurity False->None/omitted/True): the
    flag only affects FIPS-mode validation; digest bytes unchanged.
- Method: absolute spec-derived oracles (single-token == md5&mask; two-token
  == bitwise AND via majority rule), exact threshold boundaries
  (sim==threshold hits, distance==20/10 severity edges), output-contract
  pins (exact keys, round(sim,3) values). See tests/test_dedup_mutation.py.
- Lesson recorded: property-style tests (determinism, symmetry, ordering)
  are INVARIANT under global algorithm mutations and cannot kill
  vector-init/result-init mutants. Absolute oracles are required.
- New tests must be added to pytest_add_cli_args_test_selection in
  pyproject.toml or mutmut never executes them.

- **2026-08-22:** dedup.py suite added → 36.7% → **43.3%**. Next survivors: quality.py scoring weights, parser edge cases.
