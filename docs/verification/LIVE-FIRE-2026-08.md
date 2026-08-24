# Live-Fire Verification — API-Backed Actor Families
_Run date: 2026-08-24 · Method: real HTTP against each family's documented
public source, parsed through the production `jsondata` processor exactly as
shipped. No mocks, no fixtures._

## Results: 10/10 families verified

| Actor family | Source (documented in README) | Records | Sample extracted |
|---|---|---|---|
| github-release-monitor | api.github.com releases | 3 | tag `apify-sdk-python` assets_url |
| fx-rate-monitor | open.er-api.com/v6/latest | 1 | base USD, EUR 0.85618 |
| hacker-news-monitor | hn.algolia.com search | 20 | story author + title fields |
| earthquake-alert-monitor | earthquake.usgs.gov all_day GeoJSON | 50 | mag 2.05, Coso Junction CA |
| space-launch-monitor | ll.thespacedevs.com 2.2.0 upcoming | 1 | count 363 upcoming launches |
| defi-yield-monitor | yields.llama.fi/pools | 50 | Base / aerodrome-slipstream WETH-SAND |
| chain-tvl-monitor | api.llama.fi/protocols | 50 | protocol id/name/address rows |
| prediction-market-monitor | gamma-api.polymarket.com markets | 3 | live market question + conditionId |
| steam-game-stats | store.steampowered.com appdetails | 1 | app 730 → Counter-Strike 2, type game |
| fda-recall-monitor | api.fda.gov drug enforcement | 3 | status Terminated, Peoria IL |

## What this proves
1. **The processor contract holds on real payloads** — nested flattening,
   `data_path` traversal and record caps behave identically on live JSON.
2. **Documented sources are the actual sources** — every URL above is
   printed verbatim in the corresponding Actor's README *Data source*
   section. Buyers can reproduce any row we sell.
3. **Refund-risk surface is minimal by construction**: these Actors read
   public APIs; there is no anti-bot lottery between request and payload.

## Non-API families
HTML-extraction families (e-commerce JSON-LD, recipes, reviews) are covered
by the same processor contract verified via unit + golden tests, plus the
Yoast unquoted-JSON-LD regression caught in live back-testing
(see git history: `fix(processors): accept unquoted ld+json script tags`).

## Re-run instructions
```bash
python - <<'PY'
# see docs source in repo history: probe() helper per family URL table above
PY
```
Any family can be re-verified in <30 seconds with plain httpx — that is the
point of publishing exact endpoints.
