# Pry — Payments (x402)

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Payments — x402 Micropayments
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-08-30
audience:
  - operators
  - integrators
  - agents
note: Implements x402 v1. Canonical source of truth is src/pry/payments/x402/. Companion: docs/ops/API-REFERENCE.md and docs/MONETIZATION-REVIEW.md.
---

# Payments (x402)

Pry monetizes **per call** with the [x402](https://docs.x402.org/) protocol
(HTTP 402 Payment Required). No accounts, no subscriptions for the pay-as-you-go
path — pay only for what you use. There is a second, hosted path: a
**crypto subscription** (Pro/Team/Enterprise) and **bulk scrape-credit packs**.

---

## x402 Model

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
3. Client pays on-chain (0.001 USDC on Base)
4. Client retries with PAYMENT-SIGNATURE (or X-Payment-Id)
5. Server verifies on-chain → returns data
   (+ PAYMENT-RESPONSE settlement receipt)
```

**Standards surface** (from `x402/__init__.py`):

| Header | Role |
|--------|------|
| HTTP 402 | Challenge status |
| `PAYMENT-REQUIRED` | Base64 JSON manifest (server-attestable) |
| `PAYMENT-SIGNATURE` | Base64 JSON, signed, retried by client |
| `PAYMENT-RESPONSE` | Base64 settlement receipt on success |

**Server attestation** (audit #1): the manifest is signed by the server over
`(payTo, amount, network, nonce, issued_at, operation)` of every accept
(`keccak256-ecdsa-secp256k1-v1`). Signer key from `PRY_X402_ATTEST_KEY` →
`PRY_X402_FACILITATOR_KEY` → derived from `PRY_X402_ATTEST_SECRET`. With none
configured the manifest is emitted **unattested** (backward compatible).

---

## Supported Chains & Assets

`SUPPORTED_NETWORKS` / `SUPPORTED_ASSETS` in `x402/scheme.py` (CAIP-2). Verified:
**7 networks**, each with its asset set:

| Network (CAIP-2) | Family | Assets |
|------------------|--------|--------|
| `eip155:8453` (Base) | EVM | USDC, USDT, ETH, WETH |
| `eip155:1` (Ethereum) | EVM | USDC, USDT, ETH, WETH |
| `eip155:42161` (Arbitrum) | EVM | USDC, USDT, ARB, ETH, WETH |
| `eip155:10` (Optimism) | EVM | USDC, USDT, ETH, WETH |
| `eip155:137` (Polygon) | EVM | USDC, USDT, POL, WETH |
| `solana:mainnet` | Solana | USDC, USDT, SOL |
| `tron:mainnet` | TRON | USDT, TRX |

**Legacy/extra networks** referenced by the router config include
`bnb`, `avalanche`, `base-sepolia`, and (in scheme docs) `bitcoin`,
`litecoin`, `dogecoin`; the canonical acceptance surface is the 7 above.
`[REVIEW]` — `SUPPORTED_NETWORKS` is the authoritative list; some docs mention
13 networks but the runtime table is 7.

**Verification status:** EVM (EIP-7702 self-verify + external facilitators) and
Solana (SPL USDC `getTransaction` jsonParsed via `solana_verifier.py`) are real.
TRON is a `[REVIEW]` scaffold — structure/price/asset validation only (see
`VERIFICATION_STATUS`).

---

## Treasures (Operator Payee Wallets)

The **payee** is configured per chain-family. It is sourced from a secrets
backend (gopass) or env — never hardcoded. Resolution order:
gopass `x402_wallet` → gopass `evm_treasury_address` → `PRY_X402_WALLET` →
`PRY_EVM_TREASURY_ADDRESS` (for EVM; per-network overrides exist).

| Chain family | Env var | Public payee |
|---|---|---|
| EVM (all `eip155:*`) | `PRY_X402_WALLET` (or `_BASE/_ETHEREUM/_ARBITRUM/_OPTIMISM/_POLYGON`) | `0x1E3AC01d0fdb976179790BDD02823196A92705C9` |
| Solana | `PRY_X402_WALLET_SOLANA` | `G1uZFfsdxK2PuH2Em5LhRkEcptxHWe4vy5BZak67QyKv` |
| TRON | `PRY_X402_WALLET_TRON` | `TYSWXWr24QTe3c99V9dtzhe1aZTneE261p` |

Per-network EVM overrides: `PRY_X402_WALLET_BASE`, `_ETHEREUM`, `_ARBITRUM`,
`_OPTIMISM`, `_POLYGON` — each defaults to `X402_WALLET`.

### Fail-closed wallet rule

- An unset / empty / placeholder wallet is **never** emitted as `payTo` — the
  accept builders refuse and verification rejects.
- Placeholder sentinels (always rejected): `""`, `pry-default-wallet`,
  `pry-default`, `0xRMI_PLATFORM_WALLET`.
- A value not matching the network-family address format (EVM hex / Solana 44-char
  base58 / TRON `T`-prefix 34-char) is treated as unconfigured.
- An EVM address can never occupy a Solana/TRON slot (and vice-versa).
- Wallet validation uses `is_evm_address` / `is_solana_address` / `is_tron_address`
  in `x402/__init__.py`.

> **Gotcha.** `0x1E3AC0...05C9` is the **real operator payee**, not a sentinel.
> It was once mistaken for coffer's `CONFIGURED_WALLET` placeholder and listed
> in `X402_PLACEHOLDER_WALLETS`, which broke correctly-configured deployments
> (they failed closed). Do **not** re-add it there.

---

## Server-Authoritative Pricing

Prices are set server-side and resolved in `scheme.py` (`X402_PRICING`) merged
defensively in `x402_middleware/config.py` (the middleware skips gating an
operation it has no price for). The canonical 13 ops:

| Op | Price | | Op | Price |
|----|:-----:|--|----|:-----:|
| `scrape` | $0.001 | | `monitor` | $0.02 |
| `crawl` | $0.01 | | `llm_call` | $0.01 |
| `bulk_crawl` | $0.10 | | `template_execute` | $0.002 |
| `extract` | $0.005 | | `template_batch_execute` | $0.01 |
| `browser_automation` | $0.05 | | `pdf_extract` | $0.01 |
| `ocr_extract` | $0.005 | | `graphql_query` | $0.003 |
| `schema_extract` | $0.002 | | | |

**Merged total = 64 priced operations** after the domain/tier merges
(`crypto`, `data`, `sports`, `climate/research`, `events/supply`,
`app-store/news/compliance/deals/bidding`, `scrape-methods` tiers). Representative
tiers: sports all flat **$0.01/scan**; legal/real-estate/patents $0.005;
jobs/travel/search/local/news $0.002–$0.01; crypto $0.002–$0.005.

**Server-authority** is enforced in `X402Middleware`: it never trusts a
client-supplied `amount_usd` — `validate_client_amount(operation, amount_usd,
asset, network)` rejects underpayment before any facilitator call and re-checks
`is_paid` with the server-side price.

**Pricing vs README:** the README's pricing table (single scrape $0.001,
crawl per page $0.001, AI extraction $0.003, signup $0.01, CAPTCHA $0.005) is
**inconsistent** with the live `X402_PRICING` (crawl is $0.01 for up to 10 pages;
signup/CAPTCHA are not standalone priced ops in the table). `[REVIEW]` — trust
`X402_PRICING` over the README table.

---

## Pay-As-You-Go vs Hosted Subscription

| Path | Model | Payment rail | Mechanism |
|------|-------|--------------|-----------|
| **Pay-as-you-go** | per-call | x402 (per request) | 402 challenge → on-chain pay → settle → 2xx |
| **Scrape-credit packs** | bulk prepaid | x402 self-facilitation (EIP-3009 / SPL) | Buy credits → USD ledger deposit → drawdown per call |
| **Subscription** | monthly | x402 (default) or BTCPay (fallback, `PRY_BTCPAY_*`) | Invoice → activate → tier enforcement |

### Bulk scrape-credit packs
- `src/pry/commerce/billing/packs.py` — `credits * SCRAPE_CREDIT_USD == price_usd`
  (server-authoritative). The ledger stays **USD-denominated**: a pack purchase
  is a `deposit` credit for the pack's USD value; the existing `billing_service`
  drawdown/audit path is reused unchanged.
- No email / third-party processor / KYC. USDC via Pry's own self-facilitation
  rail (EIP-3009 on EVM, SPL on Solana). An API key is minted on first purchase
  (crypto signup).
- Fail-closed: `create_pack_invoice` raises `PackWalletUnconfigured` rather than
  emitting a fake payTo.
- Endpoints: `/v1/billing/purchase`, `/v1/billing/purchase/{invoice}/confirm`.

### Subscription
- `src/pry/commerce/billing/subscription.py` — monthly tiers. Payments collected
  in crypto through x402 (default) or BTCPay (when `PRY_BTCPAY_URL` + `_API_KEY`
  + `_STORE` configured). Activation records an expiry in an in-memory registry
  with optional JSON persistence (`PRY_SUBSCRIPTIONS_FILE`).
- Tiers (`billing/tiers.py`): `free`/`pro`/`team`/`enterprise` — monthly price,
  request quota, concurrent limit, feature flags, rpm cap.

### Tier enforcement
`billing/enforcer.py` (`BillingEnforcer`) enforces quota/concurrency/rpm at
request time; `pry.api.api_keys_service` binds API keys to tiers.

---

## Security & Hardening

- **Attestation**: manifests are signed (`attest_payment_required`); clients/verify
  paths can call `verify_payment_required_attestation(body, expected_signer=...)`.
  `[REVIEW]` — attestation is opt-in (emitted unattested when no signer key is set).
- **Replay hardening** (`handler.py`): a settled `tx_hash` is recorded in an
  idempotency index (`_settled_txs`) and **cannot** be replayed to mint an
  unlimited number of `payment_id`s. Swapping a fresh `payment_id` onto an
  already-used `tx_hash` is refused (`tx_hash already consumed`).
- **Payment expiry**: `PAYMENT_VALIDITY_SECONDS` (default 3600s, `PRY_X402_PAYMENT_TTL`).
  Payments recorded without `expires_at` are treated as expired (fail closed).
- **Caller binding**: payments are bound to the socket peer IP
  (`_caller_key_from_scope`) — `X-Forwarded-For` is never trusted (spoofable).
  Bound payments still expire.
- **Settlement-gating**: the middleware **only** releases the gated response
  after a successful settle (fix #3). Verify alone is insufficient.
- **Fail-closed gate**: a paid prefix with no matching price returns 500
  `payment_gate_misconfigured` (metrics: `pry_x402_gate_misconfigured_total`)
  instead of silently serving free. Startup
  `audit_route_classification` (strict mode) fails on any unclassified route.
- **Self-facilitation security**: nonce store + idempotent settlement + classified
  RPC errors. `PRY_X402_SELF_FACILITATE=1` requires a `PRY_X402_FACILITATOR_KEY`
  (gas payer) and `PRY_X402_FACILITATOR_RPC`.
- **Offline mode is dev-only**: `PRY_X402_OFFLINE=1` is **ignored** unless
  `DEBUG`/`PRY_DEBUG` is also set; bypassing verification in production is blocked.

---

## Facilitators

`FacilitatorRouter` with `DEFAULT_FACILITATORS`:
`coinbase`, `payai`, `cloudflare`, `eip-7702`. Router auto-fallbacks on
failure. Choose **one** mode:

- **(A) External facilitator** — `PRY_X402_SELF_FACILITATE=0`,
  `PRY_X402_COINBASE_VERIFY` / `PRY_X402_COINBASE_SETTLE` to coffer, or the
  public `x402.org` facilitator (default `PRY_X402_FACILITATOR`).
- **(B) Self-facilitate** — `PRY_X402_SELF_FACILITATE=1` + `_FACILITATOR_RPC`
  (EVM chain RPC) + `_FACILITATOR_KEY` (gas payer). No external facilitator /
  Coinbase CDP.

> Do not conflate `PRY_X402_FACILITATOR_RPC` (self-facilitator EVM RPC) with a
> coffer URL — coffer is only used in mode (A).
