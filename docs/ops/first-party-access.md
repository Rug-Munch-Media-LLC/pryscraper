# Internal (first-party) access — self-hosted Pry does not pay itself

**Policy:** `x402` is the **consumer** gate. Anyone self-hosting Pry must be able
to use their own deployment without paying their own payment gate. First-party
callers therefore present a signed internal credential and are served with no
payment challenge. This is also the intended **MCP path for self-hosted
deployments**.

## How it works
`src/pry/payments/x402_middleware/internal.py` accepts a request that carries:
- `X-Internal-Token` — the configured `PRY_INTERNAL_TOKEN` (fails **closed** when unset),
- `X-Internal-Timestamp` — unix seconds, inside `PRY_INTERNAL_MAX_SKEW_SECONDS` (default 300),
- `X-Internal-Signature` — `HMAC-SHA256(token, "METHOD\nPATH\nCALLER\nTIMESTAMP")` (hex),
  where `PATH` excludes the query string and `CALLER` is the socket peer the server
  sees (`127.0.0.1` for in-container callers).

Replay is refused (per-process set, shared via Redis when configured).

## Using it
```bash
# from a self-hosted box (Talos): runs the signer inside the container so the
# bound caller is 127.0.0.1
pry-internal GET "/v1/research/papers?query=cohesion+metrics"
pry-internal POST "/v1/crawl" '{"url":"https://example.com"}'

# direct call (server reachable, caller key known) — bypasses the container path
PRY_INTERNAL_BASE=https://<PRY_HOST> PRY_INTERNAL_CALLER=<CALLER_IP> \
  pry-internal GET /v1/health
```

Set `PRY_INTERNAL_TOKEN` in the deploy env (`<DEPLOY_ENV>`). An unset
token means the internal lane is **off** (by design — never "everyone is internal").

Client: `scripts/pry-internal` (installed to `pry-internal (on PATH)`).
