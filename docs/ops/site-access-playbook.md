# Site-access playbook — means & methods that WORK (keep this current)

Purpose: stop re-deriving how to reach hard sites. Everything here is a
*verified* method with the date it was proven. Add, don't replace, when a
method changes.

## Tier ladder (use in this order)
1. **plain HTTP** (httpx) — fastest; fine for open sites; **blocked by Google**.
2. **FlareSolverr** (`PRY_FLARESOLVERR_URL`, browser tier) — solves JS/challenge
   pages. Primitive: `pry.engine.flaresolverr.fetch_via_flaresolverr(url)`.
3. **Camoufox** (stealth browser) — `pry.engine.camoufox_integration`
   (`fetch` / `fetch_with_stealth`); heavier, use last.
Chain them with `pry.engine.fallback.fetch_with_fallback([...])` (returns the
first non-empty result).

## Hard-won gotchas
- **FlareSolverr can be "healthy" while its API is dead.** On 2026-10-06 the
  container reported `healthy` but `POST /v1` returned 000 even in-container.
  ALWAYS probe the endpoint before blaming the parser; a restart fixed it.
  Probe: `POST <flaresolverr>/v1 {"cmd":"request.get","url":"https://example.com"}`.
- **Google is intermittent.** The same query returns a real SERP (~1.4 MB) on
  one call and a tiny blocked page (~6 KB, 0 `<h3>`) on the next. Never assume
  one engine; ALWAYS have a fallback and a "page is too small / no <h3>" check.
- **Google's result links are opaque redirects.** Organic results are wrapped as
  `/goto?url=<token>`; the token is NOT decodable client-side — the only way to
  the real URL is to FOLLOW the redirect (bounded, keep the Google URL on
  failure). The legacy `/url?q=<url>` form still appears occasionally.
- **Google's container classes are obfuscated** (`div.g` / `.MjjYud` are gone).
  Robust extraction: find every `<h3>`, take its nearest ancestor `<a href>`.

## Verified engines (2026-10-06, browser tier up)
- **Yahoo** — `pry.engine.engine_yahoo.search_yahoo(query, n)` → returned results. âœ… most tolerant.
- **Google** — via browser tier → real SERP sometimes, blocked page often. Needs redirect-follow.
- **Seznam** — `pry.engine.engine_seznam.search_seznam` → 0 results in test.
- **searxng / DDG** — `pry.engine.web_search` (`_search_searxng`, `_search_ddg`).

## Testing without paying the consumer gate
Call the running service on the **first-party lane** (`pry-internal`) — no x402.

## Rule
A method is only "known" once it has a date + the result that proved it here.
Unverified guesses do not go in this file.
