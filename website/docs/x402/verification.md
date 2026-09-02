# Payment Verification

How Pry verifies x402 payments before releasing data.

## Flow

```
1. Client requests a paid endpoint
2. Server responds 402 Payment Required
   {
     "x402Version": 1,
     "accepts": [{
       "scheme": "exact",
       "network": "eip155:8453",
       "maxAmountRequired": "1000",   // atomic units
       "asset": "USDC",
       "payToAddress": "0x1E3AC...05C9"
     }, ...]
   }
3. Client pays on-chain (e.g. 0.001 USDC on Base)
4. Client retries with PAYMENT-SIGNATURE (or X-Payment-Id)
5. Server verifies on-chain → returns data
   (+ PAYMENT-RESPONSE settlement receipt)
```

## Header surface

| Header | Role |
|--------|------|
| HTTP 402 | Challenge status |
| `PAYMENT-REQUIRED` | Base64 JSON manifest (server-attestable) |
| `PAYMENT-SIGNATURE` | Base64 JSON, signed, retried by client |
| `PAYMENT-RESPONSE` | Base64 settlement receipt on success |

## Server attestation

Every 402 manifest is signed by the server over
`(payTo, amount, network, nonce, issued_at, operation)` using
`keccak256-ecdsa-secp256k1-v1`. Signer key resolution:
`PRY_X402_ATTEST_KEY` → `PRY_X402_FACILITATOR_KEY` → derived from
`PRY_X402_ATTEST_SECRET`. With none configured the manifest is emitted
**unattested** (backward compatible).

## Server-authoritative amounts

`X402Middleware` never trusts a client-supplied `amount_usd`:
`validate_client_amount(operation, amount_usd, asset, network)` rejects
underpayment before any facilitator call, and re-checks `is_paid` against
the server-side price. A paid prefix with no matching price fails closed
(HTTP 500), never free.

## Chain verification status

| Family | Status |
|--------|--------|
| EVM (Base, Ethereum, Arbitrum, Optimism, Polygon) | ✅ EIP-7702 self-verify + external facilitators |
| Solana | ✅ SPL USDC `getTransaction` jsonParsed (`solana_verifier.py`) |
| TRON | ⚠️ scaffold — structure/price/asset validation only |

## Ledger

Settlements are recorded in a Postgres-backed ledger (source of truth) with
a JSONL audit trail. See
[PAYMENTS.md](https://codeberg.org/RugMunchMedia/pryscraper) in the repo for
operator details.
