# ADR 0008: Coffer Consolidation

**Status:** Accepted
**Date:** 2026-08-26

## Context

Two repos (x402-coffer and x402-py) had 85% overlap. Every feature had to be written twice — same TRON verifier, same tests, same docs.

## Decision

Consolidate x402-py into x402-coffer. Coffer becomes the single source of truth.

### Why Single Repo

1. **Single TRON verifier** — not duplicated
2. **Single test suite** — not duplicated
3. **Single docs/CHANGELOG** — not duplicated
4. **Single release process** — not duplicated
5. **Single PyPI package** — `pip install x402-coffer`

### Migration

- x402-py README gets deprecation notice pointing to coffer
- Coffer includes everything x402-py had plus FastAPI server, MCP, dashboard
- "Library vs product" becomes an install mode, not a separate repo

## Consequences

- **Positive:** Eliminates duplication
- **Positive:** Faster feature development
- **Positive:** Single source of truth
- **Negative:** Existing x402-py users need to migrate
- **Neutral:** PyPI name changes (or keep x402-py as deprecated stub)
