# x402 Payments

Pry uses the [x402](https://docs.x402.org/) protocol for pay-per-call micropayments. No accounts. No subscriptions. Pay only for what you use.

## How It Works

```
1. Client requests /v1/scrape
2. Server responds: 402 Payment Required
   {
     "x402Version": 1,
     "accepts": [{
       "scheme": "exact",
       "network": "eip155:8453",
       "maxAmountRequired": "1000",
       "asset": "USDC",
       "payToAddress": "0x1E3AC...05C9"
     }]
   }
3. Client sends payment (0.001 USDC on Base)
4. Client retries with PAYMENT-SIGNATURE header
5. Server verifies on-chain → returns data
```

## Supported Networks

| Network | CAIP-2 | Assets | Verification |
|---------|--------|--------|--------------|
| **Base** | `eip155:8453` | USDC, USDT, ETH, WETH | EIP-3009 |
| **Ethereum** | `eip155:1` | USDC, USDT, ETH, WETH | EIP-3009 |
| **Arbitrum** | `eip155:42161` | USDC, USDT, ARB, ETH, WETH | EIP-3009 |
| **Optimism** | `eip155:10` | USDC, USDT, ETH, WETH | EIP-3009 |
| **Polygon** | `eip155:137` | USDC, USDT, POL, WETH | EIP-3009 |
| **Solana** | `solana:mainnet` | USDC, USDT, SOL | SPL RPC |
| **TRON** | `tron:mainnet` | USDT, TRX | TRC-20 Grid |

## Pricing

| Operation | Price | Atomic Units |
|-----------|-------|-------------|
| Single scrape | $0.001 | 1000 USDC |
| Crawl (per page) | $0.001 | 1000 USDC |
| AI extraction | $0.003 | 3000 USDC |
| Signup automation | $0.01 | 10000 USDC |
| CAPTCHA solving | $0.005 | 5000 USDC |
| Document parse | $0.002 | 2000 USDC |
| Screenshot | $0.001 | 1000 USDC |

## Discovery Endpoints

```
GET /.well-known/x402.json        → Payment manifest
GET /.well-known/agent.json       → AI agent card
GET /.well-known/x402-bazaar.json → Marketplace listing
GET /llms.txt                     → AI agent discovery
```

## Verification Methods

### EIP-3009 (EVM)
- Server checks `Transfer` event in transaction receipt
- Verifies `to` address matches configured wallet
- Confirms amount >= required

### SPL RPC (Solana)
- Queries `getTransaction` with `jsonParsed`
- Walks instructions for `transferChecked`
- Verifies mint, destination, and amount

### TRC-20 Grid (TRON)
- Queries `/walletsolidity/gettransactioninfobyid`
- Decodes `Transfer` event from logs (topic-based)
- Verifies `to` address and value
