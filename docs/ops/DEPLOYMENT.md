# Pry — Operations

[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
---
title: Pry Operations Guide
status: canonical
owner: Rug Munch Media LLC Engineering
last_updated: 2026-08-30
audience:
  - operators
  - devops-sre
note: Supersedes the prior DEPLOYMENT.md notes where they conflict. Source of truth: .env.example, pyproject.toml, docker-compose.yml.
---

# Operations

Covers self-host vs cloud, the environment-variable reference, deployment, and
scaling. Pry is primarily **self-hostable** (Docker Compose or bare metal) but is
also offered as a hosted cloud service.

---

## Self-Host vs Cloud

| Dimension | Self-host | Cloud (`api.pryscraper.com`) |
|-----------|-----------|------------------------------|
| Ownership | You run it; full privacy, no key needed (loopback or `PRY_API_KEY`) | Managed by Rug Munch Media |
| Discovery | No auth to browse MCP tools (paid calls x402) | Same |
| Payments | You point x402 at **your** treasury wallets | Settles to the operator treasury |
| Billing | Optional — enable packs/subscription against your ledger | Built in |
| Deployment | Docker Compose (recommended) / pip / uv | — |
| Datastore | SQLite (dev) / Postgres (prod), Redis optional | Managed |

---

## Environment Variable Reference

Pry is configured entirely via environment variables (loaded from `.env` in the
repo root, or the process environment). `PRY_*` vars are auto-loaded. Secrets
resolve via `secrets_backend.get_secret(name)` — gopass (`pry/<name>`) by
default, or `PRY_SECRET_BACKEND=env|file|auto`.

### Core

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_HOST` | `127.0.0.1` | Bind host |
| `PRY_PORT` | `8002` | Listen port (container); mapped to `8005` host in Compose |
| `PRY_URL` | `http://localhost:8002` | Advertised base URL |
| `PRY_DATA_DIR` | `~/.pry` | On-disk data root (quality, monitors, sessions, x402, …) |
| `PRY_ENVIRONMENT` | `dev` | `dev` / `staging` / `prod` profile |
| `PRY_DATABASE_URL` | profile default | SQLite (dev) / Postgres (prod) DSN. Prod default Postgres; SQLite needs `PRY_ALLOW_SQLITE_PROD=1` |
| `PRY_REDIS_URL` | unset | Redis for shared rate limiting + cache |

### Authentication

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_API_KEY` | unset | When set, every request must present `Authorization: Bearer` (API key or rmi JWT). When unset, **only loopback** clients allowed — every other source rejected 401 |
| `PRY_WEBHOOK_SECRET` | unset | HMAC webhook signing |

### LLM / Intelligence

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_LLM_PROVIDER_ORDER` | `zai,nvidia,groq,openrouter,kimi,cerebras,kilocode,deepseek` | Comma-separated fallback chain order (case-insensitive). Only providers with a key register |
| `PRY_LLM_RETRY_MAX_ATTEMPTS` | `2` | Per-provider retry count |
| `PRY_LLM_RETRY_BASE_DELAY` | `0.5` | Exponential backoff base (s) |
| `PRY_LLM_RETRY_MAX_DELAY` | `30` | Max backoff (s) |
| `PRY_LLM_TIMEOUT_SECONDS` | — | Per-call timeout |
| `PRY_<PROVIDER>_API_KEY` | unset | Provider keys: `OPENROUTER`, `ANTHROPIC`, `GEMINI`, `COHERE`, `MISTRAL`, `KILOCODE`, `DEEPSEEK`, `GROQ`, `KIMI`, `NVIDIA`, `NOUS`, `ZAI`, `CEREBRAS`, `MINIMAX`, `SILICONFLOW`, `OPENCODE_ZEN` (also the provider's standard env var, or gopass `pry/<name>`) |
| `PRY_OLLAMA_URL` | — | Local Ollama endpoint (always-registered free provider) |

### Web Scraping / Stealth

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_FLARESOLVERR_URL` | unset | FlareSolverr endpoint for Cloudflare bypass (sidecar) |
| `PRY_PROXY_URL` / `_TYPE` / `_USERNAME` / `_PASSWORD` | unset | Upstream proxy |
| `PRY_TOR_ENABLED` / `_SOCKS5_HOST` / `_SOCKS5_PORT` | `false` | Tor sidecar |
| `PRY_TOR_HOST` / `_PORT` / `_TIMEOUT` | `127.0.0.1` / `9050` / `30.0` | Canonical Tor fallback config |
| `WEBSHARE_PROXY_LIST` | unset (gopass `pry/webshare_proxy_list`) | Space-separated residential proxies |
| `PRY_WEBSHARE_GOPASS_PATH` | `pry/webshare_proxy_list` | gopass path fallback |
| `PRY_STEALTH_ENABLED` / `_RANDOM_USER_AGENT` / `_WEBDRIVER_OVERRIDE` / `_CANVAS_NOISE` / `_WEBRTC_DISABLE` / `_GEOLOCATION_SPOOF` | `true` | Stealth features |
| `PRY_MIN_DELAY_MS` / `_MAX_DELAY_MS` | `500` / `3000` | Human-like timing jitter |
| `PRY_MAX_RETRIES` / `PRY_MIN_QUALITY` / `PRY_RATE_LIMIT_RPM` | `3` / `50` / `120` | Retry / quality / rate limit |

### CAPTCHA

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_CAPTCHA_ENABLED` | `true` | Master toggle |
| `PRY_CAPTCHA_2CAPTCHA_API_KEY` | unset | 2captcha-style (also anti-captcha/capmonster) key |
| `PRY_CAPTCHA_CAPSOLVER_API_KEY` | unset | Capsolver (tried after 2captcha) |
| `PRY_CAPTCHA_OCR_BACKEND` | `tesseract` | `tesseract` / `easyocr` / `auto` |

### x402 Payments (the payee)

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_X402_WALLET` | gopass `x402_wallet` / `evm_treasury_address` | EVM payee (all `eip155:*`) |
| `PRY_X402_WALLET_BASE` / `_ETHEREUM` / `_ARBITRUM` / `_OPTIMISM` / `_POLYGON` | `PRY_X402_WALLET` | Per-EVM-network payee overrides |
| `PRY_X402_WALLET_SOLANA` | `""` (fail closed) | Solana 44-char base58 |
| `PRY_X402_WALLET_TRON` | `""` (fail closed) | TRON `T`-prefixed 34-char |
| `PRY_X402_FACILITATOR` | `https://x402.org/facilitator` | External facilitator URL |
| `PRY_X402_NETWORK` | `base` | Default network |
| `PRY_X402_ASSET` | `USDC` | Default asset |
| `PRY_X402_PAYMENT_TTL` | `3600` | Payment validity (s) |
| `PRY_X402_TIMEOUT` | `15` | Facilitator timeout (s) |
| `PRY_X402_SELF_FACILITATE` | `0` | `1` = self-facilitate (no external facilitator) |
| `PRY_X402_FACILITATOR_RPC` | unset | Self-facilitator EVM JSON-RPC (e.g. Base) |
| `PRY_X402_FACILITATOR_KEY` | unset | Gas-payer private key (gopass) |
| `PRY_X402_ATTEST_KEY` / `_SECRET` | unset | Server attestation signer |
| `X402_RATE_LIMIT_PER_MIN` | unset | Cap on paid-call traffic |
| `PRY_X402_BASE_RPC` / `_ETH_RPC` / `_POLYGON_RPC` / `_ARBITRUM_RPC` / `_OPTIMISM_RPC` / `_BNB_RPC` / `_AVALANCHE_RPC` / `_BASE_SEPOLIA_RPC` | public defaults | EIP-7702 self-verify RPCs |
| `PRY_X402_USD_PER_UNIT_ETH` / `_WETH` / `_ARB` / `_SOL` / `_MATIC` / `_POL` / `_TRX` | static defaults | Non-1:1 asset USD quotes (`[REVIEW]`: live oracle recommended) |
| `PRY_X402_OFFLINE` | `false` | **Dev-only**; requires `DEBUG` too |

### Sports Data

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_ODDS_API_KEY` | unset (gopass `odds_api_key`) | The Odds API key |
| `PRY_SPORTS_ODDS_CACHE_TTL_SECONDS` | `10` | In-memory TTL (~6× upstream collapse) |
| `PRY_SPORTS_ODDS_RATE_LIMIT_RPM` | `30` | Sustained upstream budget |

### Billing / Subscription

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_BTCPAY_URL` / `_API_KEY` / `_STORE` | unset | BTCPay fallback subscription backend |
| `PRY_SUBSCRIPTIONS_FILE` | in-memory | JSON persistence path for subscription registry |

### x402 Gate Auditing

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_X402_AUDIT` | strict | `strict` / `warn` / `off` for the route-classification startup audit |

---

## Deployment

### Docker Compose (recommended)

```bash
export PRY_API_KEY=$(openssl rand -hex 24)
docker compose up -d        # pry + postgres + redis + flaresolverr (+ tor profile)
curl -s http://localhost:8005/health | jq .status
```

- API on **container port 8002** → **host port 8005**.
- Compose ships hardened defaults: digest-pinned images, non-root container
  user, read-only-rootfs compatible, SIGTERM drain, healthchecks.
- `Dockerfile.apify` for the Apify Actor platform (no Playwright — the platform
  provides browser rendering).

### pip / uv

```bash
pip install pryscraper-mcp            # PyPI
# or from source:
uv sync                                # locked env from uv.lock
uv run pry serve                       # API on 127.0.0.1:8005
python -m playwright install chromium  # required for JS rendering
```

### System requirements

- Python 3.11+ (3.12 recommended).
- Playwright browsers + Linux libs for headless Chromium (the Dockerfile lists
  the pinned set).
- Optional OCR: `tesseract-ocr` + `tesseract-ocr-eng`.

---

## Scaling Notes

- **API tier is stateless** — scale replicas behind any LB. Sessions/jobs state
  lives in the database. The API key / rate-limit / payment-record state is
  either in-process (warn: each replica enforces its own bucket without Redis)
  or shared via Redis (`PRY_REDIS_URL`).
- **Shared state paths** that benefit from Redis: rate limiting, cache, and the
  x402 settlement idempotency index (which is persisted as JSONL under `PRY_DATA_DIR`).
- **Browser tiers** are the expensive path — size workers for Chromium memory
  (~300 MB per concurrent render) and prefer FlareSolverr as a sidecar pool.
- **LLM**: free-first providers; paid deepseek is the backstop. Watch the
  `cost_tracker` in `llm_usage/`.
- **Payments**: the self-facilitator (EIP-3009) broadcasts settlement with a
  gas payer; choose the RPC for the chain you accept most. Add
  `PRY_X402_RATE_LIMIT_PER_MIN` to cap paid traffic.

---

## Post-Deploy Checklist

- [ ] `/health` returns `ok`; `/ready` reflects DB + Redis connectivity
- [ ] `PRY_X402_AUDIT` boot log shows a clean route classification (no misconfigured routes)
- [ ] `/v1/x402/pricing` lists the expected operations
- [ ] Prometheus scrapes `/metrics`; alerts loaded
- [ ] One paid request verified end-to-end (402 → pay → 200)
- [ ] Webhook test delivered and signed (`POST /v1/webhooks/test`)
- [ ] Backups scheduled and restore-tested

---

## Monitoring & Observability

- `/metrics` — Prometheus endpoint.
- `/v1/diagnostics` — runtime diagnostics.
- `prometheus/`, `grafana/` — compose-monitoring stack (`compose.monitoring.yml`).
- OpenTelemetry setup in `core/observability.py` (`setup_tracing`).
- Structured logging through `core/logging_config.py` (JSON lines).
