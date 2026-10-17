# Sub-processors — Pry

**Status:** draft for legal review · **Last updated:** 2026-10-18

Pry is self-hostable. The table below lists the **categories** of third party that
may process personal data, what each can see, and where it is configured. A
self-hosted deployment that configures none of them engages none of them.

**None of these are engaged by default merely by running the code.** Every entry is
operator-configured. "Sees" describes the maximum data the category could receive
given the integration, not what is necessarily sent.

| Category | Purpose | Data visible | Configured at | Status |
|---|---|---|---|---|
| Cloud / VPS hosting | Runs the API, database, and workers | All stored data at rest, request metadata | Deployment compose / operator infra | Operator-dependent |
| LLM providers (OpenRouter, OpenAI, Anthropic) | Content extraction and vision fallback | The page content or image sent for that request; may include personal data present on the page | `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PRY_OPENROUTER_API_KEY` — `src/pry/intelligence/llm/providers/` | Optional |
| Local LLM (Ollama) | Same, self-hosted | Content stays on operator infrastructure | `PRY_OLLAMA_URL`, `OLLAMA_BASE_URL` — `src/pry/intelligence/llm/providers/local.py` | Optional, no third party |
| Proxy vendors (e.g. Webshare) | Egress IP rotation for targets | Target URLs and request headers pass through the proxy; response content returns through it | `WEBSHARE_PROXY_LIST`, `PRY_PROXY_URL` / `PROXY_URL` — `src/pry/engine/webshare_proxy.py`, `src/pry/engine/tier_chain.py` | Optional |
| Anti-bot / challenge solving (FlareSolverr) | Renders challenge pages | The target URL and response | Operator-run FlareSolverr endpoint | Optional, self-hosted |
| CAPTCHA-solving services | **Prohibited** | — | No integration exists in this repository | Not permitted |
| Email / SMTP | Alerts, operator notifications | Recipient address and message body | `smtp_host` settings — `src/pry/core/notifications.py` | Optional |
| Payments (x402 / on-chain) | Settlement | Wallet address and payment amount; no card data | Chain RPC / facilitator configuration | Optional |
| Error tracking / monitoring | Operational telemetry | Stack traces, request paths; may include URLs | Operator configuration | `[CONFIRM]` — none configured in-repo |

## Change control

Adding a sub-processor that receives personal data requires: a documented reason,
the data categories it will see, a DPA in place, and an update to this table.
Customer notification on change is `[ROADMAP]`.

## What is explicitly not a sub-processor

- Target websites being scraped — they are independent controllers of their own data.
- Public blockchains used for x402 settlement — public by design.
