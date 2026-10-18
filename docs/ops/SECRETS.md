# SECRETS — where every credential lives, how to rotate it

Operational reference for Pry. **No secret values belong in this file, in the
repo, in logs, or in chat.** Values live only in the secret backend.

## Resolution order (code)

`pry.core.settings` loads sensitive fields through
`pry.core.secrets_backend.get_secret(name)` when the field is empty:

1. `get_secret(name)` — backend selected by `PRY_SECRET_BACKEND`:
   - `gopass` (default on Talos) — reads `pry/<name>` from the gopass store;
   - `env` — reads `PRY_<NAME>`;
   - `file` — reads `$PRY_ENV_FILE`, else `$PRY_DATA_DIR/.env`;
   - `auto` — gopass if present, otherwise env.
2. `PRY_<NAME>` environment variable (pydantic `env_prefix="PRY_"`).
3. Field default (empty).

Provider SDKs also accept their native variables (e.g. `OPENAI_API_KEY`) — see
`docs/ops/DEPLOYMENT.md`. Anything supplied explicitly by env wins over the
generated defaults; never rely on the ephemeral fallbacks below in production.

## Secret inventory

| Name (`get_secret`) | gopass path | Env | Purpose | Rotatable |
|---|---|---|---|---|
| `api_key` | `pry/api_key` | `PRY_API_KEY` | Legacy master key / operator access | Yes |
| `ops_admin_key` | `pry/ops_admin_key` | — (gopass only) | Ops/admin bearer key (`docs/ops/RUNBOOK.md`) | Yes |
| `webhook_secret` | `pry/webhook_secret` | `PRY_WEBHOOK_SECRET` | HMAC signing of outbound webhooks | Yes, but it re-signs everything |
| `database_url` | `pry/database_url` | `PRY_DATABASE_URL` | Postgres DSN (embeds password) | Password only |
| `x402_wallet` | `pry/x402_wallet` | `PRY_X402_WALLET` | EVM payee address for x402 | **No** (address is on-chain identity) |
| `x402_facilitator` / `PRY_X402_FACILITATOR_KEY` | `pry/x402_facilitator_key` | `PRY_X402_FACILITATOR_KEY` | Gas-payer private key | Yes — drain/rotate funds first |
| `webshare_proxy_list` | `pry/webshare_proxy_list` | `PRY_WEBSHARE_PROXY_LIST` | Residential proxy credentials | Yes |
| `odds_api_key` | `pry/odds_api_key` | `PRY_ODDS_API_KEY` | The Odds API | Yes |
| `openrouter_api_key` | `pry/openrouter_api_key` | `PRY_OPENROUTER_API_KEY` | LLM provider | Yes |
| `openai_api_key` | `pry/openai_api_key` | `PRY_OPENAI_API_KEY` | LLM provider | Yes |
| `anthropic_api_key` | `pry/anthropic_api_key` | `PRY_ANTHROPIC_API_KEY` | LLM provider | Yes |
| `gemini_api_key` | `pry/gemini_api_key` | `PRY_GEMINI_API_KEY` | LLM provider | Yes |
| `cohere_api_key` | `pry/cohere_api_key` | `PRY_COHERE_API_KEY` | LLM provider | Yes |
| `deepseek_api_key` | `pry/deepseek_api_key` | `PRY_DEEPSEEK_API_KEY` | LLM provider | Yes |
| `groq_api_key` | `pry/groq_api_key` | `PRY_GROQ_API_KEY` | LLM provider | Yes |
| `mistral_api_key` | `pry/mistral_api_key` | `PRY_MISTRAL_API_KEY` | LLM provider | Yes |
| `kimi_api_key` | `pry/kimi_api_key` | `PRY_KIMI_API_KEY` | LLM provider | Yes |
| `nvidia_api_key` | `pry/nvidia_api_key` | `PRY_NVIDIA_API_KEY` | LLM provider | Yes |
| `nous_api_key` | `pry/nous_api_key` | `PRY_NOUS_API_KEY` | LLM provider | Yes |
| `zai_api_key` | `pry/zai_api_key` | `PRY_ZAI_API_KEY` | LLM provider | Yes |
| `cerebras_api_key` | `pry/cerebras_api_key` | `PRY_CEREBRAS_API_KEY` | LLM provider | Yes |
| `minimax_api_key` | `pry/minimax_api_key` | `PRY_MINIMAX_API_KEY` | LLM provider | Yes |
| `siliconflow_api_key` | `pry/siliconflow_api_key` | `PRY_SILICONFLOW_API_KEY` | LLM provider | Yes |
| `kilocode_api_key` | `pry/kilocode_api_key` | `PRY_KILOCODE_API_KEY` | LLM provider | Yes |
| `opencode_zen_api_key` | `pry/opencode_zen_api_key` | `PRY_OPENCODE_ZEN_API_KEY` | LLM provider | Yes |
| `captcha_2captcha_api_key` | `pry/captcha_2captcha_api_key` | `PRY_CAPTCHA_2CAPTCHA_API_KEY` | CAPTCHA solving | Yes |
| `captcha_capsolver_api_key` | `pry/captcha_capsolver_api_key` | `PRY_CAPTCHA_CAPSOLVER_API_KEY` | CAPTCHA solving | Yes |
| `captcha_nextcaptcha_api_key` | `pry/captcha_nextcaptcha_api_key` | `PRY_CAPTCHA_NEXTCAPTCHA_API_KEY` | CAPTCHA solving | Yes |
| `captcha_deathbycaptcha_username` / `_password` | `pry/captcha_deathbycaptcha_*` | `PRY_CAPTCHA_DEATHBYCAPTCHA_*` | CAPTCHA solving | Yes |
| proxy auth | `pry/proxy_username`, `pry/proxy_password` | `PRY_PROXY_USERNAME`, `PRY_PROXY_PASSWORD` | Single upstream proxy | Yes |
| DB-issued API keys | — (hashed in Postgres) | — | Customer keys `pry_...` | Yes, per key |

## Rotation procedure (gopass path)

1. Identify the name in the table; confirm consumers with
   `rg -n "<name>" src/` (never print the value).
2. Issue the new credential at the provider (revoke-after-switch where the
   provider allows overlapping keys).
3. Write it: `gopass insert -f pry/<name>` (stdin prompt, no shell history).
4. Roll the service so the settings singleton reloads:
   `docker compose restart pry` (or `systemctl restart pry`).
5. Verify: health endpoint 200, one authenticated call succeeds, and the
   provider shows traffic on the new key.
6. Revoke the old credential at the provider and record the rotation date.

Rotate all credentials immediately on suspected host compromise, not just the
one that leaked: `PRY_SECRET_BACKEND=env` deployments expose every key in
`docker inspect`.

## If a secret leaks

1. **Revoke first, investigate second** — a live key is an active incident.
2. Provider console: revoke/roll the key; for `x402_facilitator_key`, move
   remaining gas funds to a fresh address before revoking.
3. `gopass insert -f pry/<name>` + restart (steps 3–4 above).
4. Check for use: provider audit log, `pry_` key table (`revoked_at`,
   `last_used_at`), and `audit_log` / request logs for the window.
5. `gitleaks detect --no-git` over the working tree; if the value reached git,
   treat history as public and rotate — do not rewrite history as the fix.
6. Write a short incident note: secret name, window, actions, blast radius.

## Non-rotatable / special cases

- `x402_wallet` / `evm_treasury_address` — an on-chain address. Changing it
  changes who gets paid; migrate funds and update clients, do not "rotate".
- `webhook_secret` — rotating invalidates signatures for in-flight retries;
  drain the delivery queue first.
- `webhook_secret` **unset** — `_ensure_webhook_secret()` generates an
  ephemeral random secret at boot. Every restart invalidates all outstanding
  signatures, so it is effectively non-rotatable. Always set it in production.
- Ephemeral fallbacks (unset `api_key`, generated secrets) are never a
  substitute for the backend; treat their presence as a misconfiguration.
