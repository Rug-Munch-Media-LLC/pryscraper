# ADR 0003: x402 Payment Integration

**Status:** Accepted
**Date:** 2026-08-26

## Context

Pry needed a way to accept payments for API usage. Options considered:
- Stripe (fiat only, requires KYC, centralized)
- Custom crypto payments (complex, reinventing the wheel)
- x402 protocol (HTTP 402 Payment Required, crypto-native, open standard)

## Decision

Implement the x402 v1 spec as the primary payment mechanism.

### Why x402

1. **Crypto-native** — accepts USDC, USDT, SOL, TRX directly on-chain
2. **No KYC** — peer-to-peer payments without identity verification
3. **Open standard** — not controlled by any single company
4. **Multi-chain** — Base, Ethereum, Arbitrum, Optimism, Polygon, Solana, TRON
5. **MCP-compatible** — AI agents can discover and pay for tools automatically

### Implementation

- Self-hosted facilitator (no Coinbase dependency)
- Multi-asset support (USDC, USDT, native tokens)
- EIP-3009 settlement broadcast
- SPL RPC verification (Solana)
- TRC-20 Grid verification (TRON)
- Facilitator router with health-aware failover

## Consequences

- **Positive:** Sovereign payments, no intermediary, multi-chain
- **Positive:** AI agents can pay per-request automatically
- **Negative:** Must manage own settlement keys and gas
- **Negative:** Must implement on-chain verification per chain
- **Neutral:** JSONL-based payment storage (simple but not scalable to millions)
