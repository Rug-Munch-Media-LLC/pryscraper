# Transports

Pry's MCP server supports every standard MCP transport.

## Streamable HTTP

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

## SSE (Server-Sent Events)

```json
{
  "mcpServers": {
    "pry": {
      "url": "http://localhost:8002/sse"
    }
  }
}
```

Standalone SSE entry: `http://localhost:8002/sse`; messages prefix at
`/mcp/messages`.

## stdio

```bash
pry mcp --stdio
# or
pry-mcp
# or
uvx pryscraper-mcp
```

## Protocol

- MCP protocol version **2026-07-28** (JSON-RPC 2.0), with newer-revision
  tool annotations on every tool.
- Compatible with Claude, Cursor, Hermes, and any MCP client.

## Auth

- **stdio** — no network exposure, no auth needed.
- **HTTP/SSE** — loopback-only when `PRY_API_KEY` is unset; set
  `PRY_API_KEY` to require `Authorization: Bearer <key>` (API key or rmi
  JWT) for remote clients.

## Endpoints

| Path | Purpose |
|------|---------|
| `/mcp` | Streamable HTTP transport |
| `/mcp/sse` | SSE transport |
| `/mcp/messages` | Messages prefix |
| `/sse` | Standalone SSE entry |
