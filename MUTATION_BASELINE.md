# Mutation Testing Baseline — pryscraper

**Tool:** mutmut 3.7.0 · **Scope:** core parsing/extraction modules · **Recorded:** 2026-08-22

## Baseline: 36.7%

| Metric | Value |
|---|---|
| Mutants generated | 1,443 |
| Killed | 308 |
| Survived | 531 |
| No tests | 604 |
| **Score (covered)** | **36.7%** |

### Scope
`parser.py` (127) · `extraction.py` (43) · `extractor.py` (150) · `dedup.py` (129) · `quality.py` (402)

### Reading
- 604 no-test mutants: **dedup.py has no dedicated test file** ← first gap to close
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
