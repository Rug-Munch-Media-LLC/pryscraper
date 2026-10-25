# KOL discovery — what was scanned, what is blocked, what we ship

Lane: `kol-discovery`. Package: `kol_discovery/`. Registry: `kol_discovery/data/kol_registry.json`.
The X **capture** client belongs to the `x-social-ops` lane; this lane only *discovers* KOLs
and builds the registry those lanes consume.

## 1. Sources actually probed (2026-10-25, from Talos, UA `RugMunchKOLBot/0.1`)

| source | exact URL fetched | result | usable |
|---|---|---|---|
| x.com profile bio | `https://x.com/cobie` | HTTP 200, `og:title`/`og:description` present | **BLOCKED** — `robots.txt` `User-agent: *` / `Disallow: /` (plus `Crawl-delay: 1`). We do not crawl a disallowed path even though the bytes are readable. |
| x.com robots | `https://x.com/robots.txt` | HTTP 200, 2 678 B | policy input, not data |
| kolscan leaderboard | `https://kolscan.io/leaderboard` | HTTP 200, 240 267 B, Next.js RSC flight payload | **REACHABLE** — `wallet_address`, `name`, `twitter`, `telegram`; parsed without a browser |
| kolscan robots | `https://kolscan.io/robots.txt` | HTTP 404 → no crawl rules | allowed; we still self-limit to **1 request / 2 s, 15 min cache** |
| kaito.ai | `https://kaito.ai/` | HTTP 403 | blocked (WAF, JS-rendered app, no public JSON) |
| dexcheck | `https://dexcheck.io/` | HTTP 403 | blocked (Cloudflare bot management) |
| gmgn leaderboard | `https://gmgn.ai/leaderboard` | HTTP 403 | blocked (Cloudflare) — matches the existing x-social-ops stub |
| cielo.finance | `https://www.cielo.finance/` | no response (curl exit) | blocked (DNS/egress) |
| dexscreener smart-money | `https://dexscreener.com/smart-money` | HTTP 403 | blocked — **prior record** from `x-social-ops/crypto_market/kol_leaderboards.py`, not re-probed in this run |

No evasion was attempted: no proxy rotation, no cookie warming, no browser automation of a
login-walled surface. A blocked source is recorded as `blocked` with its reason and yields
zero rows — never placeholder data.

**Consequence (honest):** the only KOL-wallet source reachable without evasion pairs
*handle ↔ wallet* on a third-party board. That is `attribution: inferred`, not a statement
by the KOL. So the live registry contains **0 declared wallets** until the x-social-ops
capture lane supplies real bios/pins.

### Run result (2026-10-25, live, bounded)

| metric | value |
|---|---|
| accounts in registry | **51** (50 from `kolscan.io/leaderboard` + 1 `og:description` probe) |
| wallets declared (fact) | **0** |
| wallets inferred (never fact) | **50** |
| unique wallet keys | **50** — zero collisions, zero duplicates |
| telegram hand-offs | **15** |
| leaderboard rows fetched / accepted | 50 / 50 |
| wallet-only rows skipped (no twitter in the board row) | 4 |
| top risk score | **0.0** for all — no post history from the reachable source |

Dedupe proof (re-runnable):

```bash
python3 - <<'EOF'
import json
d = json.load(open("kol_discovery/data/kol_registry.json"))
keys = [a["key"] for a in d["accounts"]]
wallets = [w["chain"] + ":" + w["address"].lower() for a in d["accounts"] for w in a["wallets"]]
assert len(keys) == len(set(keys)) == d["stats"]["accounts"]
assert len(wallets) == len(set(wallets)) == d["stats"]["unique_wallets"]
print("no duplicate accounts or wallets:", len(keys), len(wallets))
EOF
```

## 2. Registry contract

Stable keys (the dedupe key, case-insensitive):

- account → `<platform>:<handle.casefold()>` (handles normalised from `@x`, `x.com/x/`, `twitter.com/x/`)
- wallet → `<chain>:<address.casefold()>`, chain validated (`solana` base58 32–44, `evm` `0x` + 40 hex)

Record fields: `handle, display_name, platform, followers, bio, bio_links, wallets[],
telegram, projects, first_seen, last_checked, promo_history, risk_signals, risk_score,
confidence, sources[]`.

Wallet claim fields: `chain, address, source (bio|pinned|website|leaderboard),
attribution (declared|verified|inferred), evidence (verbatim statement), evidence_url`.

### Wallet attribution is explicit-only

| case | outcome |
|---|---|
| bio says `wallet: <addr>` / `sol: <addr>` / `address: <addr>` | `declared`, evidence = that phrase |
| bio contains a bare address with no label | **refused** — an unlabelled address in a CT bio is the shilled *token contract*, not the KOL's wallet |
| third-party board pairs handle ↔ wallet | `inferred`, `is_fact=False`, requires the fetched URL as evidence |
| no evidence at all | `UnstatedWalletError` at construction time |

`FACTUAL_ATTRIBUTIONS = {declared, verified}`; only those are rendered as fact and only those
count in `stats.wallets_declared`. `merge_claims` never downgrades a statement to a guess.
Tests: `tests/test_wallet_attribution.py` (12 cases incl. the refusal contract).

## 3. Telegram

Bios are parsed for `t.me/<channel>` and stored as a single `telegram` hand-off field.
This lane does **not** maintain a Telegram registry — the telegram lanes own that; we only
pass the handle across (`stats.with_telegram`).

## 4. Risk model (weights sum to 100)

| signal | weight | definition |
|---|---|---|
| `shill_frequency` | 20 | promo posts / sampled posts |
| `contract_share` | 20 | posts carrying a contract address / sampled posts |
| `lowcap_concentration` | 15 | promos with mcap < $1M / promos |
| `undisclosed_promo` | 15 | promo share when no `#ad`/`#sponsored` marker is present |
| `rugged_promo_rate` | 15 | promoted tokens that scored high/critical on our scan |
| `deleted_post_rate` | 10 | promoted posts that vanished |
| `engagement_anomaly` | 5 | followers : median engagement worse than 1:100 |

Bands: `<25 low`, `<50 medium`, `<75 high`, `>=75 critical`. `score_risk` also returns the
ranked reasons (`signal=value -> pts`) so a call can be audited, not just trusted.
`scan_summary()` folds `rugmunch-data`-shaped rows (risk + market cap) into the three promo
counters — that join is wired but has **no live data yet** [REVIEW].

**Live scoring is currently 0 for every account** because kolscan exposes no post history,
engagement or market cap. That is a data gap, not a clean bill of health — the registry says
`risk_signals: {}`. The model itself is verified by `tests/test_risk.py` (8 cases).

## 5. Caps and politeness

| bound | value |
|---|---|
| leaderboard requests per run | 1 (15 min cache, 2 s min interval) |
| rows ingested from a board | `--limit`, default 50, hard-capped at 50 |
| accounts per run | `--max-accounts`, default 100 |
| crawl loops / pagination | none — single page only |
| retries | none; a non-200 raises and is recorded as `blocked` with the status |

## 6. Usage

```bash
python -m kol_discovery discover            # bounded live run (1 leaderboard GET)
python -m kol_discovery discover --offline  # fixtures only, no network
python -m kol_discovery report              # markdown summary
python -m kol_discovery report --json       # stats only
```

Cross-lane reuse: `feeds.optional_module("crypto_market.kol_leaderboards")` imports the
x-social-ops client when it is on the path and reports `not importable` otherwise — no
`sys.path` mutation, no vendored copy, no writes outside `kol_discovery/`.

## 7. Leftovers / [REVIEW]

1. **Bios cannot be captured here.** Until `x-social-ops` exposes a bio/pinned feed, KOL
   bios, promo history and most risk signals stay empty. `feeds.ingest_bio_rows` is the seam:
   hand it captured rows and attribution/risk light up with no code change.
2. **Kaito / DexCheck / GMGN / Cielo are WAF-blocked.** A sanctioned JS solver (FlareSolverr)
   plus a ToS review would be needed — deliberately not done in this lane.
3. **`promo_history` is defined but unpopulated** — it needs the post-history feed from (1).
4. **kolscan ToS** was not machine-readable (robots 404). We treat it as polite-read only
   (1 req / 2 s, cached, no bulk export); legal review before any scheduled crawl.
