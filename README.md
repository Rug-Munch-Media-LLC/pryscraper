<div align="center">

<img src="website/static/img/pry-logo.png" alt="PRY — web scraping, browser automation & data intelligence" width="420">

# Pry — Open any website

**Self-hosted web scraping & browser automation API with native x402 micropayments**

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](https://codeberg.org/RugMunchMedia/pryscraper/actions)
[![Tests](https://img.shields.io/badge/tests-162%2B_passing-brightgreen)](https://codeberg.org/RugMunchMedia/pryscraper)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![x402](https://img.shields.io/badge/payments-x402%20%2F%20USDC%20%2F%20SOL%20%2F%20TRX-blueviolet)](https://docs.x402.org/)
[![MCP](https://img.shields.io/badge/MCP-76_tools-purple)](https://modelcontextprotocol.io/)

**15-tier anti-bot bypass** · Cloudflare, DataDome, Akamai · **Pay-per-call API** via crypto · **76 MCP tools** · **Runs as an Apify Actor**

[Installation](#installation) · [Quickstart](#quickstart) · [Configuration](#configuration) · [MCP Server](#mcp-server) · [x402 Payments](#x402-payments) · [Registry Listings](#registry-listings) · [FAQ](docs/FAQ.md) · [Tool Catalog](docs/ops/TOOLS-CATALOG.md) · [API Reference](docs/ops/API-REFERENCE.md) · [Payments](docs/ops/PAYMENTS.md) · [Operations](docs/ops/DEPLOYMENT.md)

---

**Mirrors:**

[![Codeberg](https://img.shields.io/badge/Codeberg-mirror-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/RugMunchMedia/pryscraper)
[![GitLab](https://img.shields.io/badge/GitLab-mirror-FC6D26?logo=gitlab&logoColor=white)](https://gitlab.com/cryptorugmuncher/pryscraper)

</div>

---

## Why Pry

Every scraper breaks the moment a site turns on Cloudflare. Pry routes each
request through an adaptive **15-tier fallback chain** — plain HTTP, TLS
fingerprinting, cloudscraper, FlareSolverr, undetected-chromedriver,
Camoufox, Playwright, Googlebot emulation, Tor, premium proxies, cached
copies, AI visual scraping, mobile app API, and GraphQL discovery — escalating
only as far as the target actually requires, then remembering what worked per
domain.

### For AI Agents (MCP)

Pry exposes **76 MCP tools** across 33 categories — web scraping, data extraction,
monitoring, sports betting, legal intelligence, real estate, jobs, research, and more.
Every tool has structured input/output schemas, annotations (`readOnlyHint`,
`destructiveHint`, `idempotentHint`), and bot-readable descriptions.

**MCP URL:** `https://api.pryscraper.com/mcp/` (no account or API key needed to discover; paid calls gated by x402)

### For Humans (REST API)

```bash
# Scrape any URL (bypasses Cloudflare automatically)
curl -X POST https://api.pryscraper.com/v1/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Response: 402 Payment Required (x402)
# Pay 0.001 USDC on Base → get your data
```

---

## Installation

Pry is a Python 3.11+ package distributed on PyPI as **`pryscraper-mcp`**
(the name `pry` is taken on PyPI by an unrelated package). It installs three
command-line tools: `pry` (main CLI), `pry-mcp`, and `pryscraper-mcp` (MCP
stdio servers — identical binaries). The importable package is `pry`.

> **Prerequisites (all install methods)**
> - Python **3.11+** (3.12 recommended; the Docker image ships 3.12)
> - **Playwright browsers** for JS-rendered pages: after installing, run
>   `python -m playwright install chromium`
> - Linux system libraries for headless Chromium (Debian/Ubuntu):
>   `libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2` — the [Docker image](Dockerfile) lists the exact pinned set.
> - Optional OCR (used by the `scrape` extra): `tesseract-ocr` + `tesseract-ocr-eng`

### 1. pip (PyPI)

```bash
pip install pryscraper-mcp
```

Or, from a checkout:

```bash
pip install .            # minimal runtime
pip install -e ".[dev]"  # editable + dev tooling (pytest, ruff, mypy, …)
pip install ".[scrape]"  # optional OCR / Camoufox / pdfplumber backends
```

Verify:

```bash
pry --help
python -c "import pry; print(pry.__file__)"
pry-mcp --help          # or: pryscraper-mcp --help
```

> **Note:** `pip install pryscraper-mcp` resolves the published PyPI wheel.
> To install the bleeding-edge git state instead, use `pip install git+https://codeberg.org/RugMunchMedia/pryscraper.git` or one of the mirror URLs below.

### 2. uv

The repository is managed with **uv** (`uv.lock` is committed, `requires-python = ">=3.11"`). No `.python-version` file is pinned — uv uses the project requirement.

```bash
# Repo checkout — full locked environment (includes dev deps)
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
uv sync                       # creates .venv from uv.lock
uv run pry --help

# Or install into the current project from PyPI
uv add pryscraper-mcp
uv run pry --help

# One-shot without a project (needs the PyPI wheel published)
uvx pryscraper-mcp
```

### 3. poetry

Poetry is **not** the project's native toolchain (no `poetry.lock`, no
`[tool.poetry]` section — the repo uses setuptools + uv). To consume Pry from
a Poetry-managed project, add it as a dependency:

```bash
poetry add pryscraper-mcp                 # from PyPI
poetry add /path/to/pryscraper            # local checkout as a path dep
poetry add git+https://codeberg.org/RugMunchMedia/pryscraper.git
poetry run pry --help
```

### 4. Docker

The [Dockerfile](Dockerfile) builds a hardened, non-root image (Python 3.12,
Playwright Chromium, Tesseract, port **8002**). `docker-compose.yml` ships the
full stack — Pry plus FlareSolverr, Postgres, Redis, Prometheus, Grafana, and
Tor (`tor` behind a profile).

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

API: `http://localhost:8002` (host `127.0.0.1:8005:8002` in the compose file) ·
MCP: `http://localhost:8002/mcp/` · Health: `http://localhost:8002/health`

Single service only:

```bash
docker build -t pry .
docker run --rm -p 8002:8002 -e PRY_API_KEY=$(openssl rand -hex 24) pry
```

There is also `Dockerfile.apify` for the Apify Actor platform (no Playwright —
the Apify platform provides browser rendering).

### 5. From source (git clone + venv)

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"       # editable install, dev extras
python -m playwright install chromium
pry --help
```

Mirrors (pick whichever is reachable): **Codeberg**
https://codeberg.org/RugMunchMedia/pryscraper · **GitLab**
https://gitlab.com/cryptorugmuncher/pryscraper

---

## Quickstart

First scrape in under 5 minutes:

```bash
# 1. Install (pick one — see Installation above)
pip install pryscraper-mcp

# 2. Run the API server (or skip and use the hosted api.pryscraper.com)
pry serve                 # API on 127.0.0.1:8005

# 3. Scrape — first call returns HTTP 402 with x402 payment terms,
#    subsequent calls are gated by payment signature
pry open https://example.com
```

### As an MCP Client (AI Agents)

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/"
    }
  }
}
```

That's it. No account or API key required to discover the server — each paid call is gated per-request via x402 (pay for what you use).

### Self-hosted (Docker)

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
docker compose up -d
```

API: `http://localhost:8002` · MCP: `http://localhost:8002/mcp/`

### CLI

```bash
pry serve          # API on 127.0.0.1:8005 (see docs/ops/DEPLOYMENT.md)
pry open https://example.com
pry crawl https://docs.com --max-pages 20
```

---

## Configuration

Pry is configured via environment variables (loaded from `.env` in the repo
root, or the process environment — see `.env.example`). No API key is required
for self-hosted use, but setting one is strongly recommended.

### API key (`PRY_API_KEY`)

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_API_KEY` | unset | When **set**, every request must present a valid `Authorization: Bearer` credential (API key or rmi JWT). When **unset**, only loopback clients are allowed — every other source is rejected. |

Generate one:

```bash
export PRY_API_KEY=$(openssl rand -hex 24)
```

### x402 payee wallets

These set the **receiving addresses** for x402 micropayments. A deployment with
no wallet configured still serves requests, but **fails closed** on payment:
accept builders never emit a placeholder `payTo`.

| Var | Chain family | Format |
|-----|--------------|--------|
| `PRY_X402_WALLET` | EVM (every `eip155:*` network) | hex `0x…` |
| `PRY_X402_WALLET_SOLANA` | Solana (`solana:mainnet`) | base58, 44 chars |
| `PRY_X402_WALLET_TRON` | TRON (`tron:mainnet`) | base58check, `T`-prefixed, 34 chars |

Per-network EVM overrides: `PRY_X402_WALLET_BASE`, `PRY_X402_WALLET_ETHEREUM`,
`PRY_X402_WALLET_ARBITRUM`, `PRY_X402_WALLET_OPTIMISM`, `PRY_X402_WALLET_POLYGON`.

**Fail-closed behavior:**

- An unset or empty wallet is never emitted as `payTo` — the accept builders
  refuse and verification rejects.
- A value that does not match the network family's address format (EVM hex /
  Solana base58 / TRON `T`-prefix) is treated as unconfigured.
- An EVM address can never occupy a Solana/TRON slot (and vice-versa).
- Placeholder sentinels that are always rejected: `""`, `pry-default-wallet`,
  `pry-default`, `0xRMI_PLATFORM_WALLET`.

Example:

```bash
export PRY_X402_WALLET=0x1E3AC01d0fdb976179790BDD02823196A92705C9
export PRY_X402_WALLET_SOLANA=G1uZFfsdxK2PuH2Em5LhRkEcptxHWe4vy5BZak67QyKv
export PRY_X402_WALLET_TRON=TYSWXWr24QTe3c99V9dtzhe1aZTneE261p
```

### Other notable settings

| Var | Default | Purpose |
|-----|---------|---------|
| `PRY_X402_FACILITATOR` | `https://x402.org/facilitator` | Self-hosted x402 facilitator URL |
| `PRY_DATABASE_URL` | profile default (SQLite in dev, Postgres in prod) | Database DSN |
| `PRY_REDIS_URL` | unset | Redis for shared rate limiting |
| `PRY_DATA_DIR` | `./pry-data` | Writable data location |
| `PRY_ENVIRONMENT` | `dev` | `dev` / `staging` / `prod` profile |
| `PRY_FLARESOLVERR_URL` | unset | FlareSolverr endpoint for Cloudflare bypass |

See `docs/ops/DEPLOYMENT.md` for the full operator matrix.

### Scrape LLM backend (cost)

Pry routes its scrape/extract/parse LLM calls (extract_llm, quality_check,
extract_with_review, vision/OCR) through a **free-first fallback chain** with a
paid reliability backstop, so MCP scrapes run at near-zero cost.

- **Order env var:** `PRY_LLM_PROVIDER_ORDER` (comma-separated, case-insensitive).
  It names providers in the order Pry tries them; on a transient failure (429/5xx/
  timeout) Pry retries the current provider with backoff, then falls through to the
  next one. See `intelligence/llm/registry.py` (`_provider_order_from_env`).
- **Recommended chain (free/cheap → paid backstop):**
  `zai,nvidia,groq,openrouter,kimi,cerebras,kilocode,deepseek`
  - `zai` = GLM / z.ai — cheapest extraction tier.
  - `nvidia` (free NIM), `groq` (free), `openrouter` (free models), `kimi`,
    `cerebras`, `kilocode` — free tiers.
  - `deepseek` — **paid** reliability backstop, always LAST.
- **Activation:** a provider is only registered (and thus reachable) if its API key
  resolves. Each key can be supplied as `PRY_<NAME>_API_KEY`, the standard env var
  (e.g. `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`), or a gopass
  secret at `pry/<name>` (see `settings.py` → `_apply_secrets_backend`). A missing
  key just drops that slot from the live chain — the rest still work.
- **Overriding:** set `PRY_LLM_PROVIDER_ORDER` to any subset/order, e.g.
  `nvidia,groq,deepseek` to skip weaker free tiers, or `deepseek` alone for a
  paid-only deployment.
- **Excluded:** `opencode_zen` (free `deepseek-v4-flash-free`) is intentionally not
  listed — the fleet reserves that model as the `small_model`, not for extraction.

> [REVIEW] `deepseek`'s `cost_per_1k_*` fields are hardcoded `0.0` in providers.py
> (comment: "Paid but low cost"), so cost tracking under-reports paid spend. Engine
> cost fields are out of scope for this change.

---

## MCP Server

### Tools (76 total, 33 categories)

> Full breakdown with per-category tables and pricing: [docs/ops/TOOLS-CATALOG.md](docs/ops/TOOLS-CATALOG.md)

| Category | Count | Example Tools |
|----------|:-----:|---------------|
| **Web Scraping** | 6 | `pry_scrape`, `pry_crawl`, `pry_screenshot`, `pry_template` |
| **Sports Betting** | 13 | `pry_odds`, `pry_arbitrage`, `pry_plus_ev`, `pry_live_odds` |
| **Legal** | 5 | `pry_legal_dockets`, `pry_legal_sec`, `pry_legal_sanctions` |
| **Government** | 3 | `pry_contracts`, `pry_grants`, `pry_procurement` |
| **Retail** | 4 | `pry_amazon_product`, `pry_walmart_product`, `pry_deals` |
| **Data Enrichment** | 2 | `pry_enrich`, `pry_domain` |
| **Search** | 2 | `pry_serp`, `pry_trends` |
| **Jobs & Careers** | 2 | `pry_jobs_list`, `pry_jobs_salary` |
| **Travel** | 2 | `pry_flights_grid`, `pry_hotel_rates` |
| **Social** | 3 | `pry_sentiment`, `pry_reviews`, `pry_tiktok_trending` |
| **Crypto** | 3 | `pry_token_launches`, `pry_token_security`, `pry_cex_listings` |
| **+ 16 more** | 18 | Events, energy, freight, grocery, patents, papers, weather... |

### Tool Example

```json
{
  "name": "pry_scrape",
  "description": "Scrape any URL to clean, readable markdown, automatically bypassing Cloudflare, DataDome, Akamai, and other anti-bot systems via a 15-tier fallback chain.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {"type": "string", "format": "uri"},
      "bypass_cloudflare": {"type": "boolean", "default": true},
      "js_render": {"type": "boolean", "default": false}
    },
    "required": ["url"]
  },
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true
  }
}
```

### Transports

- **SSE** (Server-Sent Events): `https://api.pryscraper.com/sse`
- **Streamable HTTP**: `https://api.pryscraper.com/mcp/`
- **stdio**: `pry mcp serve` (or the `pry-mcp` / `pryscraper-mcp` binaries)

---

## x402 Payments

Pry uses the [x402](https://docs.x402.org/) protocol for pay-per-call micropayments.
No accounts. No subscriptions. Pay only for what you use.

### Supported Networks

| Network | Assets | Your Wallet |
|---------|--------|-------------|
| **Base** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Ethereum** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Arbitrum** | USDC, USDT, ARB, ETH, WETH | `0x1E3AC...05C9` |
| **Optimism** | USDC, USDT, ETH, WETH | `0x1E3AC...05C9` |
| **Polygon** | USDC, USDT, POL, WETH | `0x1E3AC...05C9` |
| **Solana** | USDC, USDT, SOL | `G1uZFfs...QyKv` |
| **TRON** | USDT, TRX | `TYSWXWr...E261p` |

### Operator Treasury & Configuration

These are the operator PUBLIC payee addresses for x402 across Pry, the
rmi-mcp-x402 facilitator,
and cloud-hosting signups — invoices settle to them:

| Chain family | Env var | Treasury (PUBLIC payee) |
|---|---|---|
| EVM (all `eip155:*`) | `PRY_X402_WALLET` | `0x1E3AC01d0fdb976179790BDD02823196A92705C9` |
| Solana | `PRY_X402_WALLET_SOLANA` | `G1uZFfsdxK2PuH2Em5LhRkEcptxHWe4vy5BZak67QyKv` |
| TRON | `PRY_X402_WALLET_TRON` | `TYSWXWr24QTe3c99V9dtzhe1aZTneE261p` |

**Env schema** (resolved in `src/pry/payments/x402/__init__.py`):

- `PRY_X402_WALLET` — canonical EVM payee, shared by every `eip155:*` network.
  Resolution: gopass `x402_wallet` → gopass `evm_treasury_address` →
  `PRY_X402_WALLET` → `PRY_EVM_TREASURY_ADDRESS`. Per-network overrides:
  `PRY_X402_WALLET_BASE` / `_ETHEREUM` / `_ARBITRUM` / `_OPTIMISM` / `_POLYGON`.
- `PRY_X402_WALLET_SOLANA` — Solana base58 (44 chars). Defaults `""`.
- `PRY_X402_WALLET_TRON` — TRON base58check, `T`-prefixed (34 chars). Defaults `""`.

**Fail-closed:** an unset or placeholder wallet is never emitted as `payTo` —
the accept builders refuse and verification rejects. A value that does not
match the network family's address format (EVM hex / Solana base58 / TRON
`T`-prefix) is treated as unconfigured. An EVM address can never occupy a
Solana/TRON slot.

> **Gotcha:** `0x1E3AC0…05C9` is a REAL operator payee, not a sentinel. It was
> historically mistaken for coffer's `CONFIGURED_WALLET` placeholder and listed
> in `X402_PLACEHOLDER_WALLETS`, which made a correctly configured deployment
> fail closed. The only placeholders are `""`, `pry-default-wallet`,
> `pry-default`, `0xRMI_PLATFORM_WALLET`. Do not re-add the treasury there.

### Pricing

| Operation | Price |
|-----------|-------|
| Single scrape | $0.001 |
| Crawl (per page) | $0.001 |
| AI extraction | $0.003 |
| Signup automation | $0.01 |
| CAPTCHA solving | $0.005 |

### How It Works

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

---

## Registry Listings

Pry is listed on all major MCP marketplaces:

| Registry | Status | URL |
|----------|--------|-----|
| **Glama** | ⏳ Pending | https://glama.ai/mcp |
| **Smithery** | ⏳ Pending | https://smithery.ai |
| **MCP Registry** | ⏳ Pending | https://registry.modelcontextprotocol.io/ |
| **x402 Bazaar** | ⏳ Pending | https://x402.org/bazaar |
| **Coinbase CDP** | ⏳ Pending | https://cdp.coinbase.com/x402/bazaar |

### Discovery Endpoints

```
GET /.well-known/x402.json        → Payment manifest
GET /.well-known/agent.json       → AI agent card
GET /.well-known/x402-bazaar.json → Marketplace listing
GET /llms.txt                     → AI agent discovery (llms.txt standard)
```

---

## Comparison

| Feature | Pry | Firecrawl | Scrapling | Apify |
|---------|:---:|:---------:|:---------:|:-----:|
| Anti-detection tiers | **15** | 2 | 3 | 1 |
| MCP tools | **76** | 5 | 8 | 0 |
| x402 payments | ✅ | ❌ | ❌ | ❌ |
| Self-hosted | ✅ | ❌ | ✅ | ✅ |
| Templates | **110+** | 0 | 0 | 1000+ |
| AI visual scraping | ✅ | ❌ | ❌ | ❌ |
| GraphQL discovery | ✅ | ❌ | ❌ | ❌ |
| Mobile app API | ✅ | ❌ | ❌ | ❌ |
| Crypto payments | ✅ | ❌ | ❌ | ❌ |
| Price | Pay-per-use | $49-$499/mo | Free | $49+/mo |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Pry Platform                          │
├─────────────────────────────────────────────────────────────┤
│  MCP Layer (76 tools)  │  REST API  │  x402 Payments        │
├─────────────────────────────────────────────────────────────┤
│  15-Tier Scraping Engine                                    │
│  ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐  │
│  │Direct│TLS  │Cloud│Flare│Undet│Camou│Play │Google│Tor  │  │
│  │HTTP  │FP   │scrap│Solv │Chrom│fox  │wright│bot  │     │  │
│  └─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘  │
│  ┌─────┬─────┬─────┬─────┬─────┐                           │
│  │Prem │Arch │Cache│AI   │Mobile│                          │
│  │Proxy│ive  │     │Vis  │API   │                          │
│  └─────┴─────┴─────┴─────┴─────┘                           │
├─────────────────────────────────────────────────────────────┤
│  Data: 110+ templates · 20+ domains · 7 blockchain networks │
└─────────────────────────────────────────────────────────────┘
```

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Rug Munch Media LLC.

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://rugmunch.io">Rug Munch Media LLC</a> — sovereign payments for the agentic economy.</sub>
</div>
