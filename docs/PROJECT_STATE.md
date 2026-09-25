# Project State

Last updated: 2026-09-24

## Goal

Keep Pry's public import paths stable while reducing oversized modules and
removing test-only mutation of private runtime state.

## Current focus

Continue the mechanical modularization queue after the legal-docs,
hosted-commerce, firmographics, sports-market, European-exchange, signup-verification, US-books, billing-subscription, x402-pricing, capability-detection, x402-batch, healthcare-drug-pricing, derivatives, Solana-transfer, and reconciliation tranches while preserving shrink-only gates.

## Done recently

- Split SEC EDGAR filings and OFAC sanctions into focused packages behind
  stable facades.
- Split the 451-line hosted-commerce router into focused route modules behind
  the historical import path.
- Split the 449-line firmographics module into focused source modules and
  verified legacy-vs-new scalar/orchestration parity.
- Split the 449-line books/markets parser into helpers, record builders, and
  JSON walkers; verified legacy-vs-new h2h/spreads/totals/3-way parity.
- Split the 448-line European exchange fetcher into Marathonbet, 1xBet, and
  Betfair modules with shared runtime hooks.
- Split the 446-line signup email-verification module into extraction/config,
  IMAP, temp-mail, and orchestration modules.
- Split the 445-line US-books module into registry, transport, and compatibility
  facade modules while preserving test monkeypatch seams.
- Split the 444-line billing-subscription router into shared state/models,
  invoice, account, renewal, and facade modules.
- Split the 438-line x402 pricing module into catalog, acceptance, manifest,
  legacy adapters, and facade modules.
- Split the 426-line capability detector into probes, runtime, integrations,
  storage, orchestration, and facade modules.
- Split the 423-line x402 batch module into state, Redis store, channels,
  payment orchestration, and facade modules.
- Split the 422-line healthcare drug-pricing module into config, NADAC, GoodRx,
  orchestration, and facade modules; added cache stampede locks and failure logs.
- Split the 422-line derivatives module into math, legs, teaser, if-bet,
  reverse, and round-robin modules with bounded MCP input validation and CI
  coverage for the new dataset package.
- Split the 421-line Solana transfer verifier into request, RPC, candidate,
  and verification modules with scoped CI and deterministic parity tests.
- Split the 419-line commerce reconciliation module into schemas,
  normalization, matching, reporting, LLM, and facade modules with bounded
  inputs and deterministic offline tests.
- Added explicit retry/cache seams for legal and firmographics tests.
- Reduced x402 enforcement duplication without changing ASGI response events.
- Focused legal, x402, hosting, portal, and middleware tests pass.

## Blockers

- Full-suite capability/provider tests require provider API environment
  variables to be unset on the production builder.
- The shell-quoting gate remains an untracked file owned by another change and
  is intentionally untouched.

## Next step

Run `python3 scripts/modularity_queue.py --extract` and take
`datasets/healthcare_data/insurance.py` through the same facade-preserving
split recipe.
