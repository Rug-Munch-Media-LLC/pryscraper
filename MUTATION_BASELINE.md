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
- **2026-08-22:** dedup.py suite added → 36.7% → **43.3%**. Next survivors: quality.py scoring weights, parser edge cases.
