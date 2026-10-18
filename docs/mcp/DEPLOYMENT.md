# Deploying Pry's remote MCP server (Streamable HTTP)

Status: verified 2026-10-18 against `pryscraper-mcp==3.0.0` with the official
`mcp` Python client (1.30.0). Companion: [`DISTRIBUTION.md`](DISTRIBUTION.md).

The remote transport is **Streamable HTTP**, served by `pry_mcp.asgi:app`.
The stdio entrypoints (`pry-mcp`, `pryscraper-mcp`,
`python -m pry.api.mcp_production`) are unchanged and keep working.

| Surface | Path | Auth |
|---|---|---|
| JSON-RPC (Streamable HTTP) | `POST /` | discovery public; `tools/call` needs a Bearer key |
| Server-initiated notifications | `GET /` (`Accept: text/event-stream`) | public |
| Session teardown | `DELETE /` | public (valid session required) |
| Liveness + surface counts | `GET /health` | public |

> Paths are rooted at `/`. The **full API** mounts the same handlers at
> `/mcp/`; the standalone container does not. A reverse proxy can expose it
> under any prefix (see nginx below).

## 1. Docker (single container)

```bash
docker build -t pryscraper:3.0.0 .

docker run -d --name pry-mcp \
  --restart unless-stopped \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  --tmpfs /home/pry:size=128m,mode=0700,uid=1000,gid=1000 \
  -e HOME=/home/pry -e TMPDIR=/tmp \
  -e PRY_ENVIRONMENT=prod \
  -e PRY_API_KEY="$PRY_API_KEY" \
  -e PRY_API_URL=http://host.docker.internal:8002 \
  -p 127.0.0.1:8006:8006 \
  --health-cmd 'curl -fsS http://localhost:8006/health' \
  --health-interval 30s --health-timeout 10s --health-retries 3 \
  --entrypoint uvicorn \
  pryscraper:3.0.0 pry_mcp.asgi:app --host 0.0.0.0 --port 8006 --workers 1
```

`PRY_API_URL` is the REST proxy target for tools that have no local executor.
Point it at the Pry API — not at the MCP container. `--workers 1` is the
correct default: sessions are in-process unless Redis is configured.

Prebuilt image (published releases): replace `pryscraper:3.0.0` with the
registry reference, e.g. `ghcr.io/rugmunchmedia/pryscraper:<tag>`.

## 2. Docker Compose

### Operator stack (Postgres + Redis)

```bash
POSTGRES_PASSWORD=... GRAFANA_PASSWORD=... \
  docker compose up -d pry pry-mcp
```

The `pry-mcp` service in `docker-compose.yml`:

* image `pryscraper:${PRY_IMAGE_TAG:-latest}`, `read_only: true`, non-root
  (`pry`, uid 1000), `restart: unless-stopped`, `init: true`;
* publishes `127.0.0.1:${PRY_MCP_PORT:-8006}:8006`;
* `entrypoint: uvicorn pry_mcp.asgi:app` — the image entrypoint (migrations +
  pre-migration backup) is deliberately bypassed so two containers never race
  schema changes;
* `PRY_API_URL=http://pry:8002` (sibling container);
* `PRY_REDIS_URL=redis://redis:6379/0` so `Mcp-Session-Id`s are shared if you
  ever scale beyond one worker/replica;
* healthcheck: `curl -fsS http://localhost:8006/health`;
* `depends_on`: `pry`, `postgres`, `redis` (all healthy).

Verify:

```bash
curl -fsS http://127.0.0.1:8006/health
# {"status":"ok","server":"pry-mcp","version":"3.0.0",
#  "protocol_version":"...","transports":["stdio","streamable-http","http-sse"],
#  "tools_count":99,...}
```

### Self-host profile (SQLite, no Redis)

The overlay wires `pry-mcp` in **by default**; a self-hoster gets the remote
MCP at `http://127.0.0.1:8006/` with no extra flags:

```bash
cp .env.selfhost.example .env.selfhost
./scripts/selfhost-init.sh              # generates PRY_API_KEY
docker compose -f docker-compose.yml -f docker-compose.selfhost.yml \
  --env-file .env.selfhost up -d
```

The overlay re-exports `PRY_API_KEY` into the container explicitly.
`--env-file` alone only fills Compose interpolation variables — it does not
put them in the container environment. Without that line the API and MCP
processes boot keyless and, because `PRY_ENVIRONMENT=prod`, reject every
request that arrives through the published port.

Self-host specifics: no Redis (single worker, in-process sessions), private
SQLite file under `/tmp` (never shares the API's database volume), tmpfs
`/tmp` + `/home/pry`, `PRY_MCP_SELFHOST_PORT` to change the host port.

## 3. Auth

* `initialize`, `tools/list`, `resources/list`, `prompts/list`, `ping` and
  `/health` are **public** so registries and agents can enumerate the surface.
* `tools/call` is fail-closed: `Authorization: Bearer <PRY_API_KEY>` (also
  accepted: a DB-issued `pry_...` key, a billing key, or a verified x402
  payment). Missing/wrong key → HTTP **401** with JSON-RPC `-32001`.
* Keyless loopback is a dev convenience only: it is off when
  `PRY_ENVIRONMENT=prod` and never applies through Docker's published port
  (the peer is the bridge gateway, not loopback).

```bash
KEY=...                                   # .env.selfhost / /srv/rmi-infra/.env.pry
curl -s http://127.0.0.1:8006/health
curl -s -X POST http://127.0.0.1:8006/ \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

Clients may send `Accept: application/json` (plain JSON) or
`Accept: text/event-stream` / both (single SSE `message` event). The
`Mcp-Session-Id` returned by `initialize` must be returned on later requests;
`DELETE /` ends it.

## 4. Reverse proxy (nginx) — SSE needs buffering off

Streamable HTTP replies may be SSE streams and the server sends long-lived
`GET /` streams. nginx must not buffer or chunk-decorate them.

```nginx
upstream pry_mcp { server 127.0.0.1:8006; keepalive 16; }

server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    # Standalone app is rooted at "/"; proxy under /mcp/ and strip the prefix.
    location /mcp/ {
        proxy_pass http://pry_mcp/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        # SSE: never buffer, never cache, never gzip.
        proxy_buffering off;
        proxy_cache off;
        gzip off;
        chunked_transfer_encoding on;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location = /mcp/health {
        proxy_pass http://pry_mcp/health;
    }
}
```

Point clients at `https://mcp.example.com/mcp/`. If you proxy at the root
(`location / { proxy_pass http://pry_mcp; }`) the client URL is
`https://mcp.example.com/`.

Caddy needs no special SSE config; if you front with Cloudflare, disable
"Rocket Loader" and keep the proxy read timeout above your longest stream.

## 5. Client configuration

### Claude Code (CLI)

```bash
claude mcp add --transport http pry https://mcp.example.com/mcp/ \
  --header "Authorization: Bearer $PRY_API_KEY"
```

### Claude Desktop

```json
{
  "mcpServers": {
    "pry": {
      "type": "http",
      "url": "https://mcp.example.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "pry": {
      "url": "https://mcp.example.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

### Cline (`cline_mcp_settings.json`)

```json
{
  "mcpServers": {
    "pry": {
      "type": "streamableHttp",
      "url": "https://mcp.example.com/mcp/",
      "headers": { "Authorization": "Bearer YOUR_KEY" },
      "disabled": false
    }
  }
}
```

### stdio (unchanged)

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

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized: tools/call requires an API key` | no/incorrect Bearer, or `PRY_API_KEY` not in the container | pass `-e PRY_API_KEY=...`; self-host overlay must re-export it (see above) |
| Initialize works, every `tools/call` → `has an output schema but did not return structured content` | pre-fix server: tools declare `outputSchema` but the fallback server returned only a text block | fixed in `pry_mcp/app.py` (`_attach_structured_content`); rebuild the image |
| `404 Unknown session: ...` after scaling | session created on another worker/replica; no shared store | set `PRY_REDIS_URL` (operator stack does) and keep `--workers 1` per replica |
| Tool call hangs / truncates through a proxy | SSE buffering or gzip | `proxy_buffering off; proxy_cache off; gzip off;` and a long `proxy_read_timeout` |
| `401` for a request sent from the host to the published port with no key | `PRY_ENVIRONMENT=prod` disables keyless loopback; the bridge gateway is not loopback | configure `PRY_API_KEY` |
| `GET /` returns `406` | `Accept: text/event-stream` missing | that endpoint is only the server-initiated stream; use `POST /` for JSON-RPC |
| `docker compose config` fails on the optional secrets file | `/srv/rmi-infra/.env.pry` is required on the operator box only | it is declared `required: false`; provide values via environment instead |
| Health is green but the API tools fail | `PRY_API_URL` points at `localhost` inside the MCP container | set it to the API service (`http://pry:8002`) |

## 7. Verification performed

* Clean venv: wheel built, installed with dependencies, `uvicorn
  pry_mcp.asgi:app` started from `/tmp` (non-repo cwd).
* Official `mcp` client: `initialize` → `tools/list` (99 tools) → `tools/call
  pry_actor_catalog` returned `isError=False` with `structuredContent`.
* Anonymous: `initialize`/`tools/list` 200; `tools/call` 401.
* `/health`: `status=ok`, `server=pry-mcp`, `tools_count=99`.
* `tests/test_mcp_remote.py` encodes the same checks in-process, plus the
  compose-config assertions.
