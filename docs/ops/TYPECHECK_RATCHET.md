# Typecheck Ratchet — pryscraper

> Gate: `mypy src/ pry_mcp/` (CI typecheck job) · Config: `[tool.mypy]` pyproject.toml
> Created: 2026-09-11 (enterprise audit P0.2)

## Why the scope changed

The old gate ran `mypy .` over tests/ + datasets/ + scripts/ + alembic/ and sat at
**2,789 errors** — it had never passed (0/289 CI runs), so it gated nothing. The
gate now covers the production package surface only: `src/` + `pry_mcp/` (499 files).

## Ratchet mechanism

Phase-1 discipline codes are disabled at the `[tool.mypy]` level
(`disable_error_code`) and re-enabled per-module via the strict-typed
`[[tool.mypy.overrides]]` list (which already exists for the engine core).
A module graduates by:

1. Fixing its errors for one code (e.g. `no-untyped-def`).
2. Adding it to the strict list (all codes at once) — or proposing a new
   per-code ratchet if partial.

## Baseline at scoping time (692 errors in src/+pry_mcp)

| Code | Count | Notes |
|---|---|---|
| attr-defined | 214 | 60 = implicit re-exports (facade pattern); rest = mixins (proxy_health), lxml PageElement |
| no-untyped-def | 107 | unannotated defs — highest-value first fix |
| type-arg | 103 | bare `dict`/`list` generics |
| no-untyped-call | 55 | calls into unannotated code |
| no-any-return | 40 | `Any` leaking out of returns |
| untyped-decorator | 34 | decorators on unannotated defs |
| has-type | 31 | |
| assignment | 28 | |
| unused-ignore | 17 | stale `# type: ignore` |
| arg-type / no-redef / call-overload / call-arg / return-value / misc / union-attr | ~30 | |

Hot files (fix order): misc/pryextras.py (24), payments/x402/handler_state.py (23),
misc/cli_commands.py (22), engine/proxy_health.py (22), payments/x402/facilitator_self_hosted.py (19),
core/cache.py (18), commerce/hosting/persistence.py (17), actors/automator.py (16).

## Rules

- Never remove a code from `disable_error_code` wholesale without a plan.
- Never add a module to the strict list without `mypy --strict <module>` passing locally.
- Tests/datasets re-enter gate scope only after their annotations are cleaned.
