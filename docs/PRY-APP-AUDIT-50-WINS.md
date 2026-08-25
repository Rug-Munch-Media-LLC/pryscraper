# Pry Application Audit — 50 Wins (live-tested 2026-08-25)
_Scope: the RUNNING application — API, fallback ladder, captcha, signup/keys,
x402 payments, frontend. Every finding below was verified against the live
services, not read from code._

## 🔴 CRITICAL: What live testing exposed (wins 1–10)
1. **pryscraper.com serves 503 on /api/, /health, /dashboard** — the public
   API proxy is commented out in nginx. The marketing site sells an API that
   is switched off. Re-enable proxy to the canonical backend.
2. **TWO competing deployments exist**: docker `pry` on :8005 (auth-enabled)
   AND systemd uvicorn on :8006 (from /opt/pryscraper). Kill one, crown the
   other. Today there is no single source of truth.
3. **Production runs weeks-old code**: /opt/pryscraper deploy clone is at
   `7c2dc7f` (pre-restructure). Everything shipped since — AbuseGuard,
   94-actor factory fixes, pyright zero — is NOT what's serving.
4. **Deploy pipeline does not exist**: no script/systemd flow from git main
   → /opt/pryscraper or container image. Build `scripts/deploy-api.sh`
   (rsync + venv sync + migrate + restart + healthcheck).
5. **Signup/keys route is 404 in production**: `/v1/keys` exists in repo,
   not in the deployed build. Users literally cannot sign up.
6. **Redis dependency DOWN on :8006** (`redis:false` in health) while
   :8005 has it — rate-limit/cache behavior differs between deployments.
7. **ollama:false on both** — LLM extraction features silently degraded;
   either deploy ollama or hide LLM endpoints behind capability flags.
8. **x402 gate VERIFIED WORKING** on :8006: proper 402 accepts payload,
   Base USDC, payTo `0xE24a…83bd`, eip3009. Keep this — it's earning-ready.
9. **Wallet audit**: confirm same payTo across ALL accepted networks
   (Base/ETH/Arb/Solana/TRON) — one receiving identity, documented in README.
10. **End-to-end paid scrape test**: execute one real x402 payment loop
    (settle → scrape → verify response) and record it as the launch proof.

## 🟠 FALLBACK LADDER & CAPTCHA (11–20)
11. Live tier-telemetry endpoint: expose which tier served each request
    (currently internal only) — powers status page + debugging.
12. Persist DomainTierMemory to disk/redis (today it resets on restart —
    "adaptive" forgets everything overnight).
13. Bovada E2E: the scrape returned empty via stale build; add an
    integration test asserting non-empty content for 3 hardened sites.
14. Captcha solvers: 5 registered providers verified async-correct, but
    none has a live-credentials smoke test — add optional-marked tests.
15. FlareSolverr dependency is UP (health says true) — document which tiers
    require it and alert when it's down.
16. Add per-tier timeout budgets + metric labels (which tier burns time).
17. Escalation order is fixed in docstring but enforced where? Write the
    test asserting tier order matches the documented 12.
18. Honeypot probe page: host a benign protected page we control to
    continuously verify the ladder still climbs (canary).
19. Proxy health scoring: webshare proxies have next_webshare_proxy but no
    success-rate tracking — add rolling window scoring.
20. User-agent pool freshness check (expired UA lists are a detection
    signal) — quarterly-updated fixture + test.

## 🟡 SCRAPE QUALITY (21–28)
21. Markdown output quality suite: assert headings/links/code survive for
    5 canonical pages (golden files, refreshed monthly).
22. JSON-LD extraction coverage report: % of top-1k sites with structured
    data (we know Yoast quirk; quantify the rest).
23. Content-length sanity gate: flag <200-byte "successes" as suspect.
24. Encoding correctness test suite (utf-8, latin-1, cp1252 real pages).
25. JS-rendered site sample pack: 10 URLs that REQUIRE browser tier —
    regression canary for escalation.
26. Relative→absolute URL rewriting in markdown output (verify + fix).
27. Dedup near-identical blocks (boilerplate repetition) — quality win.
28. Structured-output schema validation mode (jsonSchema input already
    supported — add conformance tests).

## 🔵 APP DESIGN & SIGNUP (29–38)
29. Self-serve signup page on pryscraper.com (form → POST /v1/keys → show
    key once). Today: no UI path to a key at all.
30. Key management UI: list/revoke/rotate (routes exist server-side).
31. Usage dashboard: per-key calls/spend chart (data already metered).
32. Pricing page on landing linking the four PPE tiers w/ examples.
33. Status page (uptime + deps: redis/flaresolverr/ollama) from health.
34. Onboarding email/webhook after key issuance (docs link + quickstart).
35. Rate-limit headers on every response (X-RateLimit-*).
36. Idempotency keys for POST /v1/batch (retry-safe clients).
37. OpenAPI description strings audit — first 3 routes read like docs.
38. Error responses: include docs URL pointer in every error body.

## 🟣 CODE QUALITY (39–46)
39. Classify 36 bare `except Exception` in src/pry (type or noqa+reason).
40. Split scraping_methods.py (1,099 lines) into engine/methods/*.
41. Split x402_middleware.py (961 lines) → payments/{enforce,config,fallback}.
42. Delete src/pry/core/db.py shim after moving db/ → core/db (14 imports).
43. Move routers/ (83 files) → api/routers/; import-smoke test all.
44. TypedDict result shapes per processor family.
45. Retire /opt/pryscraper clone after (4); systemd points at packaged app.
46. Middleware coverage 43.8% → 80% (auth paths 82–155 + metrics 388–509).

## ⚪ DOCS / SITE / LAUNCH (47–50)
47. Landing pricing section: four PPE tiers + link to Actors catalog.
48. llms.txt: append all 94 actor one-liners (agents consume this file).
49. README quickstart: curl-with-key example that actually works today.
50. STATUS.md generated from /health + suite count + last live-fire date.

## Order of attack TODAY
Blockers first: 1–5 (un-sabotage the product), 9–10 (payment proof),
29–31 (signup path). Then ladder/captcha confidence (11–20), quality
(21–28), then cleanup (39–46) and polish (47–50).
