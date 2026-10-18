# MCP clients — exact configuration

Pry exposes one MCP server through two transports:

| Transport | Endpoint / command | Use |
|---|---|---|
| Streamable HTTP | `https://api.pryscraper.com/mcp/` (self-host: `http://127.0.0.1:8006/`) | hosted or remote agents |
| stdio | `uvx pryscraper-mcp` (or `pry-mcp`) | desktop clients that spawn a local process |

Discovery (`initialize`, `tools/list`, `resources/list`, `prompts/list`,
`ping`) is public. `tools/call` requires:

```
Authorization: Bearer <PRY_API_KEY>
```

An x402 payment is accepted instead of a key. Never put the key in the URL or
commit it; pass it through the client's `headers`/`env` block.

## Protocol revision you will actually negotiate

Observed 2026-10-18 against the official MCP Python SDK 2.2.0 and a live Pry
server (matrix produced by `scripts/mcp_conformance.py`):

| Client | Requested on `initialize` | Negotiated |
|---|---|---|
| Official Python SDK `ClientSession` | `2025-11-25` (`LATEST_HANDSHAKE_VERSION`) | `2025-11-25` |
| Claude Desktop / Cursor / Cline / VS Code using the current legacy handshake | `2025-11-25` | `2025-11-25` |
| Custom/raw client asking for a supported revision | as sent | echoed verbatim |
| Any unknown revision | as sent | server ceiling `2026-07-28` |

`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25` and `2026-07-28` are
echoed when requested over raw `initialize`. The server never errors on an
unknown revision; it answers with `2026-07-28`.

The `2025-11-25` row is verified against the official Python SDK 2.2.0. Desktop
clients bundle their own SDK build, so treat their row as "the current SDK's
newest legacy handshake", not as a version pinned by Pry.

**2026-07-28 caveat.** In the current SDK, `2026-07-28` is a *modern* revision
negotiated through `server/discover`, not `initialize`. Pry does not implement
`server/discover` yet (it returns JSON-RPC `-32601`), so a client that speaks
only `2026-07-28` cannot connect. Clients that support the legacy fallback
negotiate `2025-11-25` and work normally. This is a server gap, not an SDK
limitation; `tests/test_mcp_client_conformance.py::test_modern_discover_is_not_implemented_yet`
is the canary for when it lands.

### SDK limitation (not a server bug)

`mcp.ClientSession.initialize()` takes no version argument: it always sends
`LATEST_HANDSHAKE_VERSION` and rejects a reply outside
`HANDSHAKE_PROTOCOL_VERSIONS`. The official SDK therefore cannot request
`2024-11-05`, `2025-06-18` or `2026-07-28` itself. `scripts/mcp_conformance.py`
runs those rows with raw `initialize` requests and uses the SDK for the full
session (tools, resources, prompts).

## Claude Desktop

Config: `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

Remote HTTP:

```json
{
  "mcpServers": {
    "pry": {
      "type": "http",
      "url": "https://api.pryscraper.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

stdio:

```json
{
  "mcpServers": {
    "pry": {
      "command": "uvx",
      "args": ["pryscraper-mcp"],
      "env": {
        "PRY_API_KEY": "YOUR_KEY",
        "PRY_API_URL": "https://api.pryscraper.com"
      }
    }
  }
}
```

Paste the literal key: `${VAR}` expansion inside `headers` is not guaranteed
across Claude Desktop builds.

## Cursor

Config: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project).

Remote HTTP:

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://api.pryscraper.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

stdio:

```json
{
  "mcpServers": {
    "pry": {
      "command": "uvx",
      "args": ["pryscraper-mcp"],
      "env": { "PRY_API_KEY": "YOUR_KEY" }
    }
  }
}
```

## Cline

Config: `cline_mcp_settings.json` (Cline → MCP Servers → Installed →
Configure MCP Servers).

Remote HTTP:

```json
{
  "mcpServers": {
    "pry": {
      "type": "streamableHttp",
      "url": "https://api.pryscraper.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" },
      "disabled": false
    }
  }
}
```

stdio:

```json
{
  "mcpServers": {
    "pry": {
      "command": "uvx",
      "args": ["pryscraper-mcp"],
      "env": { "PRY_API_KEY": "YOUR_KEY" },
      "disabled": false
    }
  }
}
```

## VS Code

Config: `.vscode/mcp.json` (workspace) or the user-level `mcp` setting.
VS Code uses `servers`, not `mcpServers`.

Remote HTTP:

```json
{
  "inputs": [
    {
      "id": "pry-key",
      "type": "promptString",
      "description": "Pry API key",
      "password": true
    }
  ],
  "servers": {
    "pry": {
      "type": "http",
      "url": "https://api.pryscraper.com/mcp/",
      "headers": { "Authorization": "Bearer ${input:pry-key}" }
    }
  }
}
```

stdio:

```json
{
  "inputs": [
    {
      "id": "pry-key",
      "type": "promptString",
      "description": "Pry API key",
      "password": true
    }
  ],
  "servers": {
    "pry": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pryscraper-mcp"],
      "env": { "PRY_API_KEY": "${input:pry-key}" }
    }
  }
}
```

## Raw curl (Streamable HTTP)

With `Accept: text/event-stream` every reply is a single SSE event whose
`data:` line is the JSON-RPC response; add `-N` if you want it unbuffered.

```bash
KEY="YOUR_KEY"
URL="https://api.pryscraper.com/mcp/"

# 1. initialize — capture Mcp-Session-Id
curl -sS -N -D /tmp/pry-headers.txt -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-11-25","capabilities":{},
        "clientInfo":{"name":"curl","version":"1"}}}'

SID=$(awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2}' /tmp/pry-headers.txt | tr -d '\r')

# 2. tell the server the handshake is complete (notification, HTTP 202)
curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3. list tools (public)
curl -sS -N -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4. call a tool (Bearer required)
curl -sS -N -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" \
  -H "Authorization: Bearer $KEY" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"pry_scrape","arguments":{"url":"https://example.com"}}}'
```

An unknown `Mcp-Session-Id` is rejected with HTTP 404. `DELETE` the endpoint
with the same header to end a session. A missing/invalid key on `tools/call`
returns HTTP 401 with JSON-RPC error `-32001`.

## Verify against a live server

```bash
python scripts/mcp_conformance.py --url http://127.0.0.1:8006/ --key "$PRY_API_KEY"
```

It prints the revision matrix, runs a full official-SDK session (99 tools, two
tool calls, resources, subscribe, prompts), and exits `0`/`1`.
