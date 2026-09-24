# Project State

Last updated: 2026-09-24

## Goal

Keep Pry's public import paths stable while reducing oversized modules and
removing test-only mutation of private runtime state.

## Current focus

Continue the mechanical modularization queue after the legal-docs,
hosted-commerce, firmographics, sports-market, European-exchange, signup-verification, and US-books tranches while preserving shrink-only gates.

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
`src/pry/api/routers/commerce/billing_subscription.py` through the same facade-preserving
split recipe.
