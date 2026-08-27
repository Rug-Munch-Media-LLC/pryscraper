# Networks

Pry supports 7 blockchain networks for x402 payments.

## EVM Chains

All EVM chains (Base, Ethereum, Arbitrum, Optimism, Polygon) use the same receiving address and EIP-3009 verification.

| Network | CAIP-2 | Assets | RPC |
|---------|--------|--------|-----|
| **Base** | `eip155:8453` | USDC, USDT, ETH, WETH | `https://mainnet.base.org` |
| **Ethereum** | `eip155:1` | USDC, USDT, ETH, WETH | `https://eth.llamarpc.com` |
| **Arbitrum** | `eip155:42161` | USDC, USDT, ARB, ETH, WETH | `https://arb1.arbitrum.io/rpc` |
| **Optimism** | `eip155:10` | USDC, USDT, ETH, WETH | `https://mainnet.optimism.io` |
| **Polygon** | `eip155:137` | USDC, USDT, POL, WETH | `https://polygon-rpc.com` |

## Solana

| Network | CAIP-2 | Assets | RPC |
|---------|--------|--------|-----|
| **Solana** | `solana:mainnet` | USDC, USDT, SOL | `https://api.mainnet-beta.solana.com` |

Uses SPL RPC verification (`getTransaction` jsonParsed).

## TRON

| Network | CAIP-2 | Assets | RPC |
|---------|--------|--------|-----|
| **TRON** | `tron:mainnet` | USDT, TRX | `https://api.trongrid.io` |

Uses TRC-20 Grid verification (`gettransactioninfobyid` with topic-based log decode).
