# pryscraper

A self-hosted scraping service and CLI: fetch a page, get clean Markdown or typed
JSON back, with Cloudflare handling and JS rendering available when a plain HTTP
request is not enough. Built for people who would rather run their own fetcher
than buy API credits.

**Status:** production · **Licence:** MIT for most of the tree; the stealth/browser
layer is under BSL 1.1 — read [LICENSE](LICENSE) and
[LICENSE-BSL-STEALTH](LICENSE-BSL-STEALTH).

Canonical: https://git.rugmunch.io/RugMunchMedia/pryscraper

## Quickstart

Python 3.11+.

```bash
git clone https://git.rugmunch.io/RugMunchMedia/pryscraper.git
cd pryscraper
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
pry scrape https://example.com
```

That returns Markdown on stdout with no API key and no external service. For the
HTTP API:

```bash
pry serve                     # binds PRY_HOST:PRY_PORT from your .env
curl -s "localhost:${PRY_PORT}/v1/scrape" -H 'content-type: application/json' \
  -d '{"url":"https://example.com"}' | head -40
```

Docker, single node:

```bash
docker compose up -d
```

The MCP entry points are installed alongside the CLI (`pry-mcp`,
`pryscraper-mcp`) and target the same launch code as `pry mcp --stdio`.

## What it does

- **One fetch path, three outputs.** Raw HTML, cleaned Markdown, or a typed
  extraction. Markdown cleaning strips boilerplate and reports per-check quality
  in `metadata.markdown_quality`, so a bad extraction is visible instead of silent.
- **Escalation when needed.** Plain HTTP first; FlareSolverr for Cloudflare; a
  real browser only if the previous tier failed. You pay the cost only on pages
  that need it.
- **Actors.** Named, parameterised scraping jobs live in `src/pry/actors/`, so a
  recurring target is configuration rather than new code.
- **MCP server.** Exposes scrape/extract/crawl as MCP tools for agent runtimes —
  101 tools across 33 categories, backed by 110 templates across those categories.
- **Self-host first.** Postgres/SQLite for job state, Redis optional. No vendor
  account is required for the core path.

## How it is put together

```
pry (CLI)  ──┐
HTTP API  ───┼──> src/pry/engine/      fetch tiers, cleaners, extraction
MCP       ───┘         ├── src/pry/actors/    named scrape jobs
                       ├── src/pry/api/       FastAPI routes + MCP bridge
                       └── src/pry/data/      job store, migrations (alembic)
```

## Configuration

`PRY_`-prefixed environment variables; `.env.example` and
`.env.selfhost.example` are the reference.

| Variable | Purpose |
|---|---|
| `PRY_HOST`, `PRY_PORT` | bind address for `pry serve` |
| `PRY_URL` | public base URL, used in generated links |
| `PRY_FLARESOLVERR_URL` | FlareSolverr endpoint for the Cloudflare tier |
| `PRY_CAPTCHA_ENABLED` (default **1**), `PRY_CAPTCHA_MAX_SECONDS` (60), `PRY_CAPTCHA_OCR_BACKEND` | CAPTCHA solver ladder on/off, its wall-clock cap and OCR backend |
| `PRY_LLM_PROVIDER_ORDER` | provider order for LLM-backed extraction |
| `PRY_X402_WALLET_SOLANA`, `PRY_X402_WALLET_TRON` | payout addresses if you meter access |
| `PRY_ODDS_API_KEY` | only for the odds actor |

## Known limits

- The stealth browser layer is BSL 1.1: free for non-commercial and internal use,
  not for reselling as a scraping product. The rest is MIT.
- FlareSolverr and the browser tier are optional dependencies. Without them,
  Cloudflare-protected pages fail rather than silently returning empty Markdown.
- `markdown_quality` scores readable content, not correctness — a well-formed
  page with the wrong content still scores high.
- No hosted fallback. If your egress IP is blocked, that is your egress IP.

## Development

```bash
make install
make lint
make test
```

## Licence

MIT, except the stealth/browser layer (BSL 1.1). Both files ship in the repo.

Where the owners live (retry, rate limiter, extractor), how the actor factory
composes an actor, and the full test lanes: [docs/ops/CONTRIBUTOR-MAP.md](docs/ops/CONTRIBUTOR-MAP.md).
