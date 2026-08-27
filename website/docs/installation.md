# Installation

## Docker (Recommended)

The fastest way to get started:

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

This starts:
- Pry API + MCP server
- FlareSolverr (Cloudflare bypass)
- Redis (caching, rate limiting)
- Postgres (API keys, usage tracking)
- Prometheus + Grafana (monitoring)

## CLI Install

```bash
pip install pryscraper-mcp
pry serve
```

## From Source

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pry serve
```

## System Requirements

- Python 3.11+
- Docker & Compose (for full stack)
- 4GB RAM minimum
- 10GB disk space

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRY_API_KEY` | (none) | API key for private instances |
| `PRY_X402_WALLET_BASE` | (none) | Base/EVM receiving wallet |
| `PRY_X402_WALLET_SOLANA` | (none) | Solana receiving wallet |
| `PRY_X402_WALLET_TRON` | (none) | TRON receiving wallet |
| `PRY_SELF_FACILITATE` | `1` | Enable self-hosted settlement |
| `PRY_TIMEOUT` | `60` | Request timeout (seconds) |
| `PRY_DATA_DIR` | `/app/pry-data` | Data directory |

## Verifying Installation

```bash
# Health check
curl http://localhost:8002/healthz

# MCP health
curl http://localhost:8002/mcp/health

# x402 health
curl http://localhost:8002/v1/x402/health
```
