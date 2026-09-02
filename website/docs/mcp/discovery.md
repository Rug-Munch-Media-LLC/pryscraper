# Discovery

How agents and registries discover Pry's capabilities.

## MCP tool discovery

```bash
# Health + server info (tool count, transports)
curl http://localhost:8002/mcp/health

# Full tool catalog
curl -X POST http://localhost:8002/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

## Well-known endpoints (free)

| Path | Purpose |
|------|---------|
| `/.well-known/x402.json` | x402 payment manifest |
| `/.well-known/agent.json` | AI agent card |
| `/.well-known/x402-bazaar.json` | x402 Bazaar marketplace listing |
| `/llms.txt` | llms.txt standard for agent discovery |

`llms.txt` lists all 76 tools with descriptions and is the fastest way for
an LLM to learn the full surface without a round-trip.

## Registry listings

Pry is registered in the major MCP registries with machine-readable
payloads kept in sync from `pry_mcp/tools.py`:

- `server.json` — MCP registry entry (`io.rugmunch/pry`)
- `glama.json` — Glama listing
- `pulsemcp.json` — PulseMCP listing
- `registry_manifest.json` — aggregated manifest (76 tools / 33 categories)

Install one-liners:

```bash
uvx pryscraper-mcp        # stdio, no install
pip install pryscraper-mcp
```
