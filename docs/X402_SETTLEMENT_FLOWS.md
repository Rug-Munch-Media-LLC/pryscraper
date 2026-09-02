# X402 Settlement Flows

Pry supports two settlement paths for x402 payments. Both produce the same
settlement receipt (appended to `settlements.jsonl`) and both are covered by
the same idempotency key (`tx:{network}:{tx_hash}`).

## Path A — Pay-direct-then-prove (default, PROVEN)

1. The payer sends a **plain USDC transfer** (standard ERC-20 `transfer`) to
   the Pry treasury wallet.
2. The payment gate verifies the transfer on-chain via the EIP-7702 receipt
   check (tx hash + recipient + amount + confirmation).
3. `settle_payment` issues the settlement receipt.

**Status: PROVEN working** — a real production transaction settled through
this path on 2026-09-01. No extra configuration is required beyond the
treasury wallet; this is the default flow.

## Path B — Canonical EIP-3009 (SelfFacilitator broadcast)

1. The payer signs an **EIP-712 `transferWithAuthorization`** message
   (EIP-3009) for USDC instead of broadcasting a transfer.
2. Pry's `SelfFacilitator` (`src/pry/payments/x402/self_facilitator.py`)
   submits the signed authorization on-chain via
   `settle_with_details`, paying the gas itself.
3. On success the same settlement receipt is issued.

### Requirements

Path B requires the operator to configure:

| Env var | Purpose |
|---|---|
| `PRY_X402_FACILITATOR_RPC` | JSON-RPC endpoint used to broadcast the EIP-3009 authorization |
| `PRY_X402_FACILITATOR_KEY` | Private key of the gas-paying wallet (funds the broadcast) |

Optional tuning: `PRY_X402_EIP712_NAME` / `PRY_X402_EIP712_VERSION` (EIP-712
domain, default `USD Coin` / `2`) and `PRY_X402_ALLOW_TESTNETS` (opt-in
testnet acceptance).

Self-facilitation is refused at startup when self-facilitate mode is enabled
but the RPC or key is missing — the module fails closed rather than
pretending to facilitate.

### Current live status

**The live container currently has ZERO `SELF_FACILITATOR`-related
environment variables configured** (verified via `docker exec pry printenv |
grep -c SELF_FACILITATOR` → `0`). Path B is therefore **not enabled in
production today**; all live settlements go through Path A.

To enable Path B an operator must:

1. Provision a dedicated gas wallet funded with the native chain token.
2. Set `PRY_X402_FACILITATOR_RPC` to a JSON-RPC endpoint for the target
   network(s).
3. Set `PRY_X402_FACILITATOR_KEY` to the gas wallet's private key (via the
   secrets manager / container environment — never in code or git).
4. Restart the service and confirm the self-facilitator startup check passes.

## Customer notification (settlement webhooks)

By default customers must poll for settlement. To receive a push
notification when a settlement succeeds, set:

| Env var | Purpose |
|---|---|
| `PRY_SETTLEMENT_WEBHOOK_URL` | HTTPS endpoint that receives a POST with the settlement receipt on every NEW successful settle (empty/unset = disabled) |

Deliveries are HMAC-signed (`X-Pry-Signature: sha256=...`, requires
`PRY_WEBHOOK_SECRET`), retried with backoff, and dead-lettered on failure.
Webhook failures never affect the settlement result itself.
