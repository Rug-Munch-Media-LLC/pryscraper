# Contributor map — tests, actor composition, canonical module owners

One page so the next reader finds the owner instead of writing a fourth copy.
Generated from the tree on 2026-10-25; every path below was checked with `test -e`.

## 1. Run the tests

```bash
make install          # editable install + dev extras
make test             # pytest tests/ -v --cov=. --cov-report=term-missing
pytest tests/test_engine.py -k retry -q   # single module / filter
make check            # lint (ruff) + typecheck (mypy) + test
make ci               # precommit + test, what CI runs
```

Full guide, markers and the fuzz/contract/k6 lanes: [ops/TESTING.md](TESTING.md).
Local dev workflow and env vars: [ops/DEVELOPMENT.md](DEVELOPMENT.md).

## 2. How the actor factory composes an actor

112 actors live in `actor_factory/actors/`. **None of them is written by hand end
to end** — `actor_factory/generator.py` turns one `ActorSpec` into a complete
`.actor/` package.

| Stage | Module | Produces |
|---|---|---|
| 1. Spec in | `actor_factory/generator.py` (`generate_actor`) | the generation plan |
| 2. Schema + copy | `generator_sections.py`, `generator_copy.py`, `generator_data_sources.py` | `.actor/INPUT_SCHEMA.json`, store copy |
| 3. Examples | `generator_examples.py` | `.actor/` example inputs/outputs |
| 4. Store README | `generator_readme.py`, `generator_readme_render.py` | `.actor/README.md` |
| 5. PPE billing | `economics.py` | pay-per-event wiring in the generated runner |
| 6. Guardrails | `abuse_guard.py` | spending-limit / abort handling |
| 7. Actor body | `actor_factory/actors/<slug>/src/main.py` | the only per-actor code you write |

Resulting package: `.actor/actor.json` (spec v1) + `INPUT_SCHEMA.json` +
`Dockerfile` + `README.md` + `CHANGELOG.md`, plus `src/main.py` calling
`PPEScraperRunner`. Build one with `make actor-build`; methodology and the
three-layer test approach are in [strategy/ACTOR-FACTORY.md](../strategy/ACTOR-FACTORY.md)
and the store rules in [strategy/ACTOR-STANDARDS.md](../strategy/ACTOR-STANDARDS.md).

## 3. Canonical owners — rate limit / retry / extractor

There are many copies of each. These four are **the** owners; import or extend
them rather than adding a fifth. Measured inventory and per-copy differences:
[UTILITY-OWNERS.md](../UTILITY-OWNERS.md).

| Capability | Canonical module | Do not |
|---|---|---|
| retry / backoff + `Retry-After` | `src/pry/engine/retry.py`, `src/pry/engine/retry_after.py` | inline `2**attempt` sleeps in callers |
| rate limit — outbound scraping | `src/pry/core/ratelimit.py` | per-module token buckets |
| rate limit — inbound API | `rmi-backend: app/core/rate_limiter.py` (`UnifiedRateLimiter`) | a second limiter in pry's API layer |
| HTML→text extraction | `src/pry/engine/extractor.py` | new `*_extract.py` helpers in routers |

Schema/OCR/PDF extraction are siblings of the extractor under `src/pry/engine/`
(`schema_extract.py`, `ocr_extractor.py`, `pdf_extractor.py`).
