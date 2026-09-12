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

## Phase 1 progress (2026-09-12)

Measured with the phase-1 codes re-enabled (`--enable-error-code` for
`no-untyped-def`, `type-arg`, `no-any-return`, `no-untyped-call`,
`untyped-decorator`, `attr-defined`, `has-type`, `assignment`, `unused-ignore`,
`arg-type`, `no-redef`, `call-overload`, `call-arg`, `return-value`, `misc`,
`union-attr`). The repo gate (`mypy src/ pry_mcp/`) stays green throughout.

| File | Before | After | Fixed |
|---|---|---|---|
| `src/pry/misc/pryextras.py` | 24 | 2 | `no-untyped-def` ×10, `type-arg` ×10, `no-untyped-call` ×2 |
| `src/pry/payments/x402/handler_state.py` | 23 | 0 | `attr-defined` ×17, `no-untyped-def` ×5, `has-type` ×1 |
| `src/pry/misc/cli_commands.py` | 22 | 0 | `no-untyped-def` ×11, `no-untyped-call` ×10, `type-arg` ×1 |

Remaining (2, `pryextras.py`): `no-untyped-call` on `PryScraper()` and
`SchemaExtractor()` — their `__init__` is untyped in `engine/scraper.py` /
`engine/extractor.py`; fix requires annotating those modules (out of scope for
this phase). `handler_state.py` used the mixin pattern: host-supplied attributes
are declared as bare class-level annotations on `StateMixin` (no runtime effect).

## Phase 2 progress (2026-09-12)

Same measurement method (16 phase-1 codes re-enabled via `--enable-error-code`).
Repo gate (`mypy src/ pry_mcp/`) stays green throughout.

| File | Before | After | Fixed |
|---|---|---|---|
| `src/pry/engine/proxy_health.py` | 22 | 0 | `attr-defined` ×17, `no-any-return` ×5 |
| `src/pry/payments/x402/facilitator_self_hosted.py` | 19 | 0 | `attr-defined` ×13, `no-any-return` ×4, `has-type` ×2 |
| `src/pry/core/cache.py` | 18 | 0 | `type-arg` ×10, `no-untyped-def` ×4, `no-any-return` ×4 |
| `src/pry/commerce/hosting/persistence.py` | 17 | 0 | `assignment` ×17 |
| `src/pry/misc/pryextras.py` | 2 | 0 | `no-untyped-call` ×2 (cross-module) |

Cross-module fix: annotated `PryScraper.__init__` (`engine/scraper.py`) and
`SchemaExtractor.__init__` (`engine/extractor.py`) with `-> None`; `_ultimate`
declared `Any` (lazily-imported optional dep). `pryextras.py` now clean.

Patterns used: mixin host-state declared as bare class-level annotations
(`ProxyHealthMixin`, `SelfHostedMixin`) — no runtime effect; SQLAlchemy legacy
`Column` rows annotated `Any` in `_save_invoice`; bare `dict`/`OrderedDict`
generics parameterized.

Remaining in touched files (pre-existing, untouched methods, out of scope):
`engine/scraper.py` 9 (`type-arg` ×7, `no-any-return` ×2),
`engine/extractor.py` 1 (`no-any-return`). Next hot files: `actors/automator.py`
(16), `payments/x402/facilitator_self_hosted.py` done, `engine/proxy_health.py`
done.

