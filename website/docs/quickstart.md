# Quickstart

Three paths. Each ends with HTTP 200.

## 1. MCP client

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/"
    }
  }
}
```

Then call a tool:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"pry_scrape","arguments":{"url":"https://example.com"}}}
```

```json
{"jsonrpc":"2.0","id":1,
 "result":{"content":[{"type":"text","text":"{\"success\":true,\"data\":{\"markdown\":\"# Example Domain...\",\"metadata\":{\"url\":\"https://example.com\",\"method\":\"direct\",\"title\":\"Example Domain\",\"offset\":0,\"total\":1256}}}"}]}}
```

`tools/list` is keyless. `tools/call` needs an x402 payment or an API key.

## 2. Self-hosted

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

Services: API `http://localhost:8005`, MCP `http://localhost:8005/mcp/`, health `http://localhost:8005/health`. The container listens on 8002; `PRY_SELFHOST_PORT` sets the host port.

## 3. CLI

```bash
pip install pryscraper-mcp
PRY_X402_ENABLED=false PRY_API_KEY=devkey pry serve
pry open https://example.com
pry crawl https://docs.com --max-pages 20
```

`pry open` fetches the page and prints the result. `pry serve` binds `127.0.0.1:8005`.

## 4. Hosted REST (x402)

```bash
curl -i -s -X POST https://api.pryscraper.com/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
# HTTP/1.1 402 Payment Required
# accepts[] quotes network, asset, maxAmountRequired (atomic), payToAddress
```

Pay the quoted amount, then repeat the request with `PAYMENT-SIGNATURE`. The body is the same `{"success":true,"data":{...}}` shape shown above.

## Next

- [Installation](installation) — all install methods.
- [Configuration](configuration) — env vars, wallets, networks.
- [API reference](api/scrape) — endpoints and schemas.
- [x402](x402/overview) — payment flow.
- [MCP server](mcp/overview) — 99 tools.
