# MCP clients — exact configuration

Pry exposes one MCP server through two transports:

| Transport | Endpoint / command | Use |
|---|---|---|
| Streamable HTTP | `https://api.pryscraper.com/mcp/` (self-host: `http://127.0.0.1:8006/`) | hosted or remote agents |
| stdio | `uvx pryscraper-mcp`, `pry-mcp`, `pry-mcp --stdio`, `pry mcp --stdio`, or `python -m pry.api.mcp_production` | desktop clients that spawn a local process |

Discovery (`server/discover`, `initialize`, `tools/list`, `resources/list`,
`prompts/list`, `ping`) is public. `tools/call` requires:

```
Authorization: Bearer <PRY_API_KEY>
```

An x402 payment is accepted instead of a key. Never put the key in the URL or
commit it; pass it through the client's `headers`/`env` block.

## Protocol revisions — dual-era (legacy + modern)

Pry answers **both** protocol idioms on the same endpoint:

* **Legacy** (`2025-11-25` and earlier) — the `initialize` handshake, then a
  session. Unchanged.
* **Modern** (`2026-07-28`) — the revision is declared per request (in
  `params._meta` and the `MCP-Protocol-Version` header); clients may call
  `server/discover` first. No `initialize` and no session are required.

Observed 2026-10-18 against a live Pry server (matrix and modern session
produced by `scripts/mcp_conformance.py`):

| Client | Opens with | Negotiated |
|---|---|---|
| Official Python SDK 2.x (modern) | `server/discover` | `2026-07-28` |
| Modern client without discovery | any RPC with `_meta` / header | served statelessly at `2026-07-28` |
| Official Python SDK `ClientSession` (2.x, pinned in this repo) | `initialize` `2025-11-25` | `2025-11-25` |
| Claude Desktop / Cursor / Cline / VS Code using the legacy handshake | `initialize` `2025-11-25` | `2025-11-25` |
| Custom/raw legacy client asking for a supported revision | `initialize`, as sent | echoed verbatim |
| Any unknown revision on `initialize` | `initialize`, as sent | server ceiling `2026-07-28` |
| Modern request declaring an unsupported revision | any RPC | `-32022` UnsupportedProtocolVersionError |

`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25` and `2026-07-28` are
echoed when requested over raw `initialize`. The legacy handshake never errors
on an unknown revision; it answers with `2026-07-28`.

### Modern handshake — `server/discover`

Discovery is public and stateless: no API key, no `Mcp-Session-Id`. The result
is defined once in `pry_mcp/constants.py` (`discover_result()`):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "resultType": "complete",
    "supportedVersions": ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"],
    "capabilities": {
      "tools": {"listChanged": true},
      "resources": {"subscribe": true, "listChanged": true},
      "prompts": {"listChanged": true},
      "logging": {}
    },
    "_meta": {
      "io.modelcontextprotocol/serverInfo": {"name": "pry", "version": "3.0.0"}
    },
    "instructions": "Pry provides web scraping, extraction, and crypto-market intelligence tools. ...",
    "ttlMs": 3600000,
    "cacheScope": "public"
  }
}
```

`initialize` and `server/discover` share one capabilities definition, so the two
eras cannot drift. A modern request whose declared revision is not in
`supportedVersions` gets JSON-RPC `-32022` with
`data: {"supported": [...], "requested": "..."}`; the client retries with a
mutually supported version. `tools/call` still requires the Bearer key (or an
x402 payment) in either era.

**stdio serves both eras.** Every stdio boot path (`pry-mcp`,
`pryscraper-mcp`, `pry-mcp --stdio`, `pry mcp --stdio`,
`python -m pry.api.mcp_production`) runs the same dual-era JSON-RPC loop
(`pry_mcp/fallback_protocol.py`). A modern-only client can therefore run
`server/discover` -> `tools/list` -> `tools/call` over stdio without sending
`initialize`, and a legacy client keeps its `initialize` handshake unchanged.
The loop is chosen whenever the installed SDK cannot serve modern discovery
(the 1.x SDK is legacy-only and 2.x dropped the decorator `Server` API), so the
two eras cannot be split by which SDK a deployment happens to resolve.

### SDK limitation (not a server bug)

`mcp.ClientSession.initialize()` takes no version argument: it always sends its
own `LATEST_HANDSHAKE_VERSION` and rejects a reply outside
`HANDSHAKE_PROTOCOL_VERSIONS`. The installed 2.x SDK still tops out at
`2025-11-25`; the modern `2026-07-28` path is exercised with raw
`server/discover` / `_meta` requests (the conformance runner's modern session).

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

### Modern (2026-07-28) flow — no `initialize`

Every request declares the revision twice: in `params._meta` and in the
`MCP-Protocol-Version` header. Discovery is public and stateless (no
`Mcp-Session-Id`); only `tools/call` needs the key.

```bash
URL="https://api.pryscraper.com/mcp/"
MODERN=(-H 'Content-Type: application/json' -H 'Accept: application/json'
        -H 'MCP-Protocol-Version: 2026-07-28')
META='"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}'

# 1. discover — versions, capabilities, serverInfo (no key)
curl -sS -X POST "$URL" "${MODERN[@]}" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"server/discover\",\"params\":{$META}}"

# 2. list tools (no key)
curl -sS -X POST "$URL" "${MODERN[@]}" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{$META}}"

# 3. call a tool (Bearer required)
curl -sS -X POST "$URL" "${MODERN[@]}" -H "Authorization: Bearer $KEY" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",
       \"params\":{$META,\"name\":\"pry_scrape\",\"arguments\":{\"url\":\"https://example.com\"}}}"
```

A modern request declaring a revision outside `supportedVersions` returns
JSON-RPC `-32022` with `data.supported` and `data.requested`; retry with one of
the listed versions.

An unknown `Mcp-Session-Id` is rejected with HTTP 404. `DELETE` the endpoint
with the same header to end a session. A missing/invalid key on `tools/call`
returns HTTP 401 with JSON-RPC error `-32001`.

## Verify against a live server

```bash
python scripts/mcp_conformance.py --url http://127.0.0.1:8006/ --key "$PRY_API_KEY"
```

It prints the legacy revision matrix, runs a full official-SDK session
(99 tools, two tool calls, resources, subscribe, prompts), runs a
2026-07-28-only modern session (discover -> list -> call), and exits `0`/`1`.
