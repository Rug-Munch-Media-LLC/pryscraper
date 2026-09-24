# Pry — Go-Live Runbook (MCP / x402 Marketplaces)

> Ordered checklist to list Pry on Actify + Glama + MCP Registry and start earning.
> Owner: Rug Munch Media LLC Engineering · Updated 2026-08-30
> Companion: [REGISTRY-SUBMIT](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/scripts/registry-submit.md) · [SUBSCRIBE](https://git.rugmunch.io/RugMunchMedia/pryscraper/blob/main/scripts/register_pry.py) · [DEPLOYMENT](DEPLOYMENT.md)

Every box below must be **checked and verified with evidence** before the next
step. Do not skip ahead — a listed-but-unverified marketplace will reject the
listing or, worse, surface an honest-but-broken server to paying agents.

---

## 0. Sources of truth (reconcile before touching a listing)

| Trigger | File | Field |
|---|---|---|
| Tool count | `pry_mcp/tools.py` → `PRY_TOOLS` | `len(PRY_TOOLS)` (currently **76**) |
| Categories | `src/pry/api/registry_metadata.py` → `_categorize` | `get_tools_by_category()` |
| Live URLs | `README.md` / `website/static/img/pry.png` | `api.pryscraper.com`, `pryscraper.com` |

Do **not** guess the tool count. Derive it:
```bash
.venv/bin/python -c "from pry_mcp.tools import PRY_TOOLS; print(len(PRY_TOOLS))"
```
If the count drifts again, bump every metadata file in lockstep:
`registry_manifest.json`, `llms.txt`, `server.json`, `glama.json`, `pulsemcp.json`.

---

## 1. Real treasury configured

- [ ] `x402_receiving_wallet` / `X402_WALLET` set to a real, operator-controlled address (not a placeholder `[INTERNAL]`/`0x0`).
- [ ] `pry_buy_pack` output returns a **non-empty `payToAddress`** for at least one pack. If empty ⇒ operator wallet is not configured — **do not publicize**.
- [ ] Supported networks/assets match what the wallet actually accepts (see `docs/ops/MCP_X402_AUDIT.md`).
- [ ] Treasury address **verified by hand** on-chain (never trust the terminal echo).

## 2. Prices server-authoritative

- [ ] Pricing is served by the backend (not hardcoded in a client/listing). `pry_x402_pricing` returns real atomic-unit prices per tool.
- [ ] Every paid prefix has an entry; free reads (e.g. `pry_balance`) are marked free.
- [ ] Pack prices in `pry_buy_pack` (`starter`, etc.) match `pry_x402_pricing` for the same credits.
- [ ] Price changes flow from a single server-side source; no drift between pricing, listing payloads, and README.

## 3. End-to-end settle verified

- [ ] `pry_buy_pack` → pay on-chain (USDC on the quoted network) → `confirm` with tx hash → balance credited.
- [ ] `pry_balance` reflects the credited USD after settlement (e.g. $5.00 after a 5,000-credit starter pack).
- [ ] A paid operation (e.g. `pry_scrape`) executes after settlement and returns a non-error payload.
- [ ] Round-trip runs through **both** the x402 path and the API-key path (fail-closed both ways).
- [ ] Low-balance flag fires at the configured threshold; exhausted balance refuses to spend.

## 4. Manifest links live

- [ ] `registry_manifest.json`: `website=https://pryscraper.com`, `docs=https://docs.pryscraper.com`, `icon=https://pryscraper.com/img/pry.png` — all **resolve** (no subdomain `LEGACY_API_DOMAIN`/`docs.LEGACY_API_DOMAIN` dead refs).
- [ ] `icon` path serves a real asset: confirm `website/static/img/pry.png` exists (Docusaurus mounts `static/` → `/img/pry.png` = `/img/pry.png` on the live site).
- [ ] `llms.txt`, `server.json`, `glama.json`, `pulsemcp.json` carry no `[INTERNAL]`, `LEGACY_API_DOMAIN`, or `docs.LEGACY_API_DOMAIN`.
- [ ] Tool count in every metadata file equals `len(PRY_TOOLS)` (76) — grep for the previous count and fix any stragglers.

## 5. Submission payloads real

- [ ] `registry_submissions/mcp_listing.json` — `icon`, `banner`, `website`, `docs`, `mcp.url` all real live URLs, no placeholders.
- [ ] `registry_submissions/x402_listing.json` — `seller.website/icon/banner`, `contact.website`, and every `services[].endpoint` are real live URLs.
  - Confirmed live: `/v1/scrape`, `/v1/crawl`; others route to `https://api.pryscraper.com/mcp/`.
- [ ] Validate every JSON: `python3 -m json.tool <file> > /dev/null && echo OK`.

## 6. Smoke test

```bash
# Discovery (public, no auth)
curl -s https://api.pryscraper.com/mcp/ | head
curl -s https://api.pryscraper.com/health | jq .status          # expect ok

# Tool count sanity (via server tools list / registry_manifest count == 76)
# Paid path (x402-signed or API-keyed) on one non-trivial operation, e.g.
curl -s -X POST https://api.pryscraper.com/v1/scrape \
     -H "Authorization: Bearer $PRY_API_KEY" \
     -H "Content-Type: application/json" -d '{"url":"https://example.com"}' | jq .
```
- [ ] Health returns `ok`; MCP discovery returns a tool list.
- [ ] Discovery is reachable with **no** API key (pay-per-call gating happens per operation).
- [ ] At least one paid operation returns 200 against a real URL.
- [ ] No `[REVIEW]` / placeholder address ever appears in a **successful** response.

## 7. List + start earning

- [ ] Submit `registry_submissions/mcp_listing.json` to **Actify**, **Glama**, **MCP Registry** (and Smithery/MCP Market per `../../scripts/register_pry.py`).
- [ ] Submit `registry_submissions/x402_listing.json` to the x402 bazaars (x402.org/bazaar, x402scan).
- [ ] Confirm each marketplace rendered the listing (tool count, icon, prices) — not just that the upload succeeded.
- [ ] Watch first settlement; verify funds land in the treasury.

---

## Rollback plan

| Situation | Action |
|---|---|
| Listing shows dead URL / count drift | Re-fix the metadata file(s) and **re-submit**; the manifest fields are the source a marketplace renders. |
| `payToAddress` empty / wallet wrong | Suspend listings immediately; `grep -rn '[INTERNAL]\|payToAddress'` the payloads; fix wallet config; do not publish a broken pay path. |
| Settlement credited but operation 5xx | Pause x402 for that prefix (`PRY_X402_AUDIT` / route classification), refund manually, fix server, resume. |
| Price/credit mismatch | Take the listing down (Glama/MCP dashboards), correct the single server-side source, re-verify E2E, re-list. |
| Marketplace-side scrape failure (their crawler can't reach `/mcp/`) | Confirm `api.pryscraper.com` is publicly reachable + not Cloudflare/geo-blocked to the marketplace's IP; whitelist if needed. |

**Golden rule**: a listing should never point at an unverified treasury, a
placeholder address, or a price that the server does not itself enforce.
