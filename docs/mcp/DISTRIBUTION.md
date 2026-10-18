# MCP distribution — entrypoints, transports, registries

Status: verified 2026-10-18 against `pryscraper-mcp==3.0.0`.

## Working entrypoints

| Transport | Command | Proven by |
|---|---|---|
| stdio | `pryscraper-mcp` / `pry-mcp` | `tests/test_mcp_distribution.py::test_stdio_entrypoint_handshake` (installed wheel) |
| stdio | `python -m pry.api.mcp_production` | same test; also Smithery `commandFunction` |
| HTTP (MCP only) | `uvicorn pry_mcp.asgi:app --port 8006` | `test_http_initialize_and_tools_list` |
| HTTP (full API) | `uvicorn pry.api.api:app` → MCP at `/mcp/` | `GET /mcp/health` returns `tools_count: 99` |

`pry.api.mcp_production` is a stdio-only compatibility shim: it has **no**
module-level `app`, so `uvicorn pry.api.mcp_production:app` fails with
`Attribute "app" not found`. Use `pry_mcp.asgi:app` for a standalone HTTP MCP
server.

`pry mcp --stdio` is **not** wired into `pry.misc.cli:main` (the dispatcher only
routes `proxy` and `wallets` to the click group). Use `pry-mcp` or
`python -m pry.api.mcp_production` until the dispatcher is fixed.

## Auth

- `initialize`, `tools/list`, `resources/list`, `prompts/list`, `ping`, `/health`
  are public so registries and agents can enumerate the surface.
- `tools/call` requires `Authorization: Bearer <PRY_API_KEY>` (or a DB `pry_...`
  key, or a verified x402 payment). Anonymous and wrong keys return HTTP 401
  with JSON-RPC `-32001`. Keyless loopback is allowed only when no key is
  configured and the environment is not `prod`.

## Manifests

| File | Consumed by | Notes |
|---|---|---|
| `server.json` | official MCP registry | validated against the 2025-12-11 schema; description ≤100 chars; `icons` points at `logo-mark-v2.png` |
| `smithery.yaml` | Smithery | `startCommand.type: stdio`, `commandFunction` runs `python3 -m pry.api.mcp_production` |
| `glama.json` | Glama | schema is `https://glama.ai/mcp/schemas/server.json`; requires `maintainers` (GitHub usernames) |
| `pulsemcp.json` | PulseMCP submission bundle | tool list == `PRY_TOOLS` (99) |
| `registry_submissions/mcp_listing.json` | mcp.so / directory listing | verified asset URLs only |

All manifests are asserted against `pry_mcp.tools.PRY_TOOLS` by
`tests/test_mcp_distribution.py`.
