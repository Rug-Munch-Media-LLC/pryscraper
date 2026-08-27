# ADR 0004: TRON TRC-20 Verifier Design

**Status:** Accepted  
**Date:** 2026-08-26

## Context

TRON payments were scaffolded (accepted but never verified on-chain). Needed a real TRC-20 USDT verifier.

## Decision

Implement a topic-based TRC-20 Transfer event verifier using the TRON Grid RPC.

### Why Topic-Based

1. **Universal** — works with both raw and parsed RPC formats
2. **Consistent** — same pattern as EVM log decoding
3. **Robust** — doesn't rely on Trongrid-specific `event_name` field

### Implementation

- Query `/walletsolidity/gettransactioninfobyid`
- Walk `log[]` for entries with `topics[0] == TRANSFER_EVENT_TOPIC0`
- Decode `from` (topics[1]), `to` (topics[2]), `value` (data)
- Compare decoded `to` against expected recipient (hex)
- Verify amount >= required

## Consequences

- **Positive:** Real on-chain TRON verification
- **Positive:** No TRON SDK dependency (httpx only)
- **Positive:** Works across RPC providers
- **Negative:** TRON address encoding (base58check) requires normalization
