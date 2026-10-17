# Quickstart

Three paths. Each ends with HTTP 200 and the body below.

## 1. Hosted API (x402)

No account. The first call returns `402` with a quote; your client pays it and retries.

```bash
curl -i -s -X POST https://api.pryscraper.com/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
```

```http
HTTP/1.1 402 Payment Required
```

```json
{
  "x402Version": 1,
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "asset": "USDC",
    "maxAmountRequired": "1000",
    "payToAddress": "0x1E3AC...05C9",
    "resource": "https://api.pryscraper.com/v1/scrape"
  }],
  "description": "Single URL scrape",
  "instructions": "payment required: send 1000 USDC (atomic units) ... then retry this request with the PAYMENT-SIGNATURE header"
}
```

Pay `maxAmountRequired` on `network`, then repeat the same request with the payment header:

```bash
curl -s -X POST https://api.pryscraper.com/v1/scrape \
  -H 'Content-Type: application/json' \
  -H "PAYMENT-SIGNATURE: $PAYMENT_SIGNATURE" \
  -d '{"url":"https://example.com"}'
```

```json
{
  "success": true,
  "data": {
    "markdown": "# Example Domain\n\nThis domain is for use in illustrative examples...",
    "metadata": {"url": "https://example.com", "method": "direct", "title": "Example Domain", "offset": 0, "total": 1256}
  }
}
```

The quote fields come from `build_multi_asset_accepts` (`src/pry/payments/x402/scheme/pricing/accepts.py`). The 200 body comes from the `scrape` handler (`src/pry/api/routers/scraping/scraping.py`).

## 2. Self-host (Docker Compose)

```bash
git clone https://codeberg.org/RugMunchMedia/pryscraper.git
cd pryscraper
cp .env.selfhost.example .env.selfhost
./scripts/selfhost-init.sh
PRY_SELFHOST_PORT=8005 docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost up -d
```

```bash
KEY=$(grep '^PRY_API_KEY=' .env.selfhost | cut -d= -f2)
curl -s http://localhost:8005/v1/scrape \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
```

```json
{"success": true, "data": {"markdown": "# Example Domain\n\n...", "metadata": {"url": "https://example.com", "method": "direct", "title": "Example Domain", "offset": 0, "total": 1256}}}
```

Check the server before the first call:

```bash
curl -s http://localhost:8005/healthz
# {"status": "ok", "version": "<APP_VERSION>"}
```

Self-host default is `PRY_X402_ENABLED=false`, so no 402 is returned (`src/pry/api/kill_switches.py`). The container listens on 8002; `PRY_SELFHOST_PORT` sets the host port (`docker-compose.selfhost.yml`).

## 3. MCP client

Hosted:

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/"
    }
  }
}
```

Local:

```json
{
  "mcpServers": {
    "pry": {
      "command": "pry-mcp"
    }
  }
}
```

Call `pry_scrape`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"pry_scrape","arguments":{"url":"https://example.com"}}}
```

```json
{"jsonrpc":"2.0","id":1,
 "result":{"content":[{"type":"text","text":"{\"success\":true,\"data\":{\"markdown\":\"# Example Domain...\",\"metadata\":{\"url\":\"https://example.com\",\"method\":\"direct\",\"title\":\"Example Domain\",\"offset\":0,\"total\":1256}}}"}]}}
```

`tools/list` needs no key. `tools/call` needs an API key or an x402 payment (`llms.txt`, `pry_mcp/app.py`). The tool-to-route map is `pry_mcp/tool_routes.py`.

## Next

- [Concepts](CONCEPTS.md) — page, tiers, x402, actors, templates.
- [Testing](ops/TESTING.md) — run the suite, read the gates.
- [Tool catalog](ops/TOOLS-CATALOG.md) — all 99 tools.
