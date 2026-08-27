# Configuration

## Environment Variables

All configuration is env-var-first with `PRY_` prefix.

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_API_KEY` | (none) | Global API key. Unset = loopback-only mode |

When `PRY_API_KEY` is unset, only loopback clients can access the API. Set it to enable remote access with key authentication.

### Wallet Configuration

| Variable | Chain | Description |
|----------|-------|-------------|
| `PRY_X402_WALLET_BASE` | Base | USDC/USDT/ETH receiving address |
| `PRY_X402_WALLET_ETHEREUM` | Ethereum | ETH receiving address |
| `PRY_X402_WALLET_ARBITRUM` | Arbitrum | ARB/ETH receiving address |
| `PRY_X402_WALLET_OPTIMISM` | Optimism | ETH receiving address |
| `PRY_X402_WALLET_POLYGON` | Polygon | POL/MATIC receiving address |
| `PRY_X402_WALLET_SOLANA` | Solana | USDC/USDT/SOL receiving address |
| `PRY_X402_WALLET_TRON` | TRON | USDT/TRX receiving address |

### Payment Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_SELF_FACILITATE` | `1` | Enable self-hosted settlement |
| `PRY_X402_FACILITATOR_KEY` | (none) | EVM private key for settlement gas |
| `PRY_X402_FACILITATOR_RPC` | (none) | EVM RPC endpoint for settlement |
| `PRY_X402_OFFLINE` | `false` | Dev-only verification bypass |

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_HOST` | `0.0.0.0` | Bind address |
| `PRY_PORT` | `8002` | Bind port |
| `PRY_TIMEOUT` | `60` | Request timeout (seconds) |
| `PRY_DATA_DIR` | `/app/pry-data` | Data directory |
| `PRY_LOG_LEVEL` | `INFO` | Log level |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_RATE_LIMIT_RPS` | `10` | Requests per second per client |
| `PRY_RATE_LIMIT_BURST` | `20` | Burst allowance |

## Config File

You can also use a JSON config file:

```json
{
  "x402_wallet": "0x...",
  "x402_wallet_solana": "...",
  "x402_wallet_tron": "...",
  "self_facilitate": true,
  "rate_limit_rps": 10
}
```

Load with: `PRY_CONFIG_FILE=/path/to/config.json`
