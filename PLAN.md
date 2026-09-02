<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright (c) 2026 Rug Munch Media LLC -->
# PLAN.md — PryScraper

> Current sprint. Update weekly (see AGENTS.md).

## Current Sprint Goals (audit-driven)
1. **Decompose FallbackMCPServer** — split `pry_mcp/fallback_server.py`
   (1,036L god-class) into focused modules (transport, tool dispatch,
   resource/prompt handling) following the tools.py split pattern.
2. **Strengthen router tests** — parametrized import + route-registration
   smoke test across all routers; fix test-ordering state bleed so tests are
   order-independent.
3. **Target the 392 no-test mutants** — highest-value mutation target: lines
   the selected engine tests never execute (see MUTATION_BASELINE.md). Add
   tests, re-measure, bump baseline.
4. **Expand mypy strict** — add modules to the `[[tool.mypy.overrides]]`
   strict list as they pass `--strict`; never remove without an ADR.

## Next Priorities (ranked)
1. FallbackMCPServer decomposition (largest maintainability debt).
2. Router smoke test + test-ordering isolation (stability gate).
3. No-test mutant burn-down (raise mutation score above 71%).
4. mypy strict ratchet (audit win #7 continuation).
5. Finish package migration (SYSTEM-AUDIT-V2 A1–A8: db/, routers/, captcha/,
   x402/, llm_providers/, commerce/ → src/pry).

## Completed (recent git log)
- MCP auth gate, browser pooling, migration tests, DevOps hardening.
- Engine perf: blocking calls fixed, pooled client, async DNS, cache caps.
- Redis-backed MCP session store (horizontal scaling).
- x402 offline-mode guard in production.
- Pre-push hook 155s → 3.8s (secret detection + boundaries only).
- tools.py god-file split (6,079L → per-domain modules).
- Signed portal tokens replace email-only auth (magic-link pattern).
- Postgres-backed x402 ledger (audit #2 complete) + settlement webhooks.
- Admin-role RBAC + audit log; key revocation.

## Last Updated
2026-09-02
