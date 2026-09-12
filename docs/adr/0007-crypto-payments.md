# ADR 0007: Crypto Payment Providers

**Status:** Accepted
**Date:** 2026-08-26

## Context

Beyond x402, some users want to pay with Bitcoin, Ethereum, or other cryptocurrencies via traditional payment processors.

## Decision

Integrate three crypto payment providers with automatic failover:

1. **Coinbase Commerce** — trusted brand, good UX
2. **NowPayments** — 150+ coins, no KYC
3. **BTCPay Server** — self-hosted option for privacy

### Implementation

- `CryptoPaymentRouter` routes charges across providers
- Falls back to next provider on failure
- Webhook verification per provider
- REST endpoints at `/v1/payments/crypto`

## Consequences

- **Positive:** Accepts BTC, ETH, SOL, and 150+ other coins
- **Positive:** Automatic failover for reliability
- **Positive:** Self-hosted option (BTCPay)
- **Negative:** Each provider requires API key configuration
- **Negative:** Webhook handling complexity
