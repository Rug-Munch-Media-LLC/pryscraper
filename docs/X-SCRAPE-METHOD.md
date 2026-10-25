# X (Twitter) scraping with pry — the honest method

Captured 2026-10-25 from Talos (netcup), plain HTTP client, `curl` + a
browser UA string, no cookies, no proxies. Status codes below are recorded
observations, not expectations.

## Verdict

**Syndication first, guest-token never, HTML never.**

| Rank | Surface | Verified | Usable data |
| ---- | ------- | -------- | ----------- |
| 1 | `syndication.twitter.com/srv/timeline-profile/screen-name/<handle>` | `200` (373 KB `text/html`, Next.js page; the `__NEXT_DATA__` island is [INFERRED] from the Next.js payload, not yet parsed cleanly — see Verification status) | author, text, id, `created_at`, counts [INFERRED from surface purpose + Next.js payload] |
| 2 | `cdn.syndication.twimg.com/tweet-result?id=<id>` | `200` (920 B JSON) | author, text, id, `created_at`, `favorite_count` |
| — | `x.com/<handle>` (plain GET) | `200` (211 KB) but a **JS-only shell**: `og:description` present, zero `data-testid` nodes, sign-in prompt | none |
| — | `api.twitter.com/1.1/guest/activate.json` (no bearer) | `403 {"code":200,"message":"Forbidden."}` | none |
| — | `api.twitter.com/2/timeline/profile` (no guest token) | `404` (X error page) | none |

Both syndication surfaces are unauthenticated public embed endpoints: the same
ones `publish.twitter.com` uses for embedded timelines. They are the only paths
implemented here.

## Rate limits — observed, not guessed

- First two sequential `timeline-profile` requests: `200 373246 B`, `200 324635 B`.
- Fourth request inside ~2 minutes: `429` (20-byte body).
- `tweet-result` answered `200 920 B` once, then `200` with a **2-byte `{}`
  body** under the same rapid probing — an empty-object soft block, not an error.
- No `Retry-After` was interpreted; a 100 s cool-off was not enough to clear the
  429 in the test window, so the block is longer than 100 s. `[REVIEW]` exact
  window unknown — treat as minutes, not seconds.

Operating budget: **1 request per handle per minute, hard stop on 429**, then
exponential backoff (60 s → 300 s → 900 s). Never retry a 429 in a loop; pry
returns `blocked.ratelimit` and stops.

## Legal / ToS boundary — where pry stops

- **Out of scope: authenticated GraphQL** (`/i/api/graphql/...` with a logged-in
  session, `ct0`/`auth_token` cookies, or the official web client's public bearer
  token). Using a user's cookies or impersonating X's own web client is a ToS
  violation, not a scraping technique. `XAdapter` will never do it; the refusal
  code is `blocked.tos` and the adapter is simply not written.
- Out of scope: `nitter` mirrors and any third-party relay — unverifiable
  provenance, and a "tweet" from a mirror is not evidence.
- In scope: the public embed surfaces above, at human pacing, with attribution
  links back to `x.com` kept in every record.
- Respect X's robots/ToS on your own deployment; this document describes what
  the endpoints return, not a licence to ignore them.

## Rotation / render settings that succeeded

- `js_render=False` — both syndication endpoints are plain HTTP; a headless
  browser buys nothing and costs 200× the bandwidth.
- `bypass_cloudflare=False` — no challenge was served; FlareSolverr was not used.
- No proxies needed at ≤1 req/min/handle. For fan-out across many handles,
  rotate per-handle with a per-egress-IP token bucket, because the limit observed
  is IP-scoped.
- UA: a current desktop Chrome string; no cookies, no `Authorization` header.

## Envelope contract

Every `x_*` adapter returns exactly one shape (`schema_version: 1`):

```json
{"schema_version": 1, "ok": true, "source": "syndication.timeline",
 "data": {"handle": "...", "count": 20, "tweets": [...]},
 "error": null, "http_status": 200, "fetched_at": "2026-10-25T11:20:00+00:00"}
```

Failure is always `ok: false` with `error.code` in
`blocked.auth | blocked.tos | blocked.ratelimit | blocked.challenge | no_data`
and `data: null`. A partially parsed payload is never returned as a tweet.

## Modules

- `src/pry/actors/x_envelope.py` — the one envelope shape + refusal table.
- `src/pry/actors/x_parse.py` — `__NEXT_DATA__` extraction, no I/O.
- `src/pry/actors/x_syndication.py` — `fetch_profile_timeline(handle, client=None)`.
- `src/pry/actors/x_tweet.py` — `fetch_tweet(tweet_id, client=None)`.
- `tests/test_x_scrape.py` + `tests/fixtures/x/` — offline only, stubbed client.

## Known gaps

- No pagination: the syndication page exposes a cursor pry does not yet follow.
- Profile metadata (bio, followers) is not parsed; only tweets are normalized.
- `x.com` HTML is deliberately unused, so no profile-page fallback exists.

## Verification status (append, 2026-10-25)

- Probed live from Talos with `curl`, browser UA, no cookies: `timeline-profile`
  `200`/373246 B and `200`/324635 B on the first two calls, then `429` (20 B) and
  still `429` after a 100 s cool-off. `tweet-result` gave `200`/920 B with real
  tweet fields first, then `200` with a 2-byte `{}` soft-block body.
- `x.com/<handle>`: `200`/211664 B, `og:description` present, **no**
  `data-testid` nodes and a sign-in prompt → JS-only shell, zero tweet data.
- `api.twitter.com/1.1/guest/activate.json` (POST, no bearer): `403`
  `{"code":200,"message":"Forbidden."}`. `api.twitter.com/2/timeline/profile`
  (no guest token): `404` X error page.
- Tests: `PYTHONPATH=src python3 -m pytest tests/test_x_scrape.py -q` →
  **8 passed, 2 skipped**. The two skipped tests are the timeline-parsing tests:
  the 429 block prevented a clean recorded `__NEXT_DATA__` fixture, so that
  parser ships with login-wall / bad-JSON coverage only. It is **not** proven
  against a live payload — `[REVIEW]` re-capture when the IP block clears.
- The `tweet_result.json` fixture is reconstructed from the live `200`/920 B
  response (fields observed in the response head; the `user` object was
  truncated in the capture, so `name`/`screen_name` were filled from the tweet
  URL `x.com/jack/status/20`). It is marked `_fixture_note` in the file; the
  live response is 920 B and contains more fields than the fixture.
- `pry-mcp pry_scrape("https://x.com/elonmusk", js_render=True,
  bypass_cloudflare=True)` failed at the bridge: `Connection closed` — no
  render result was obtained, so no claim is made about rendered X pages.

## Timeline adapter — PROVEN (2026-10-25 10:24Z)

Cool-off after the 429, then one plain-UA GET of
`https://syndication.twitter.com/srv/timeline-profile/screen-name/AnthropicAI`:

- HTTP 200, 145,365 B `text/html`, one `__NEXT_DATA__` island, 110 `id_str`.
- `normalize_tweets()` yields 20 tweets with distinct ids, real `created_at`
  (`Fri Oct 23 13:40:39 +0000 2026`) and real metrics (likes 240 / rt 12 /
  replies 27 / quotes 6). Fixture: `tests/fixtures/x/timeline_page.html`.

Status: **works**, not `experimental`. Caveat unchanged — the surface rate-limits
hard: three calls inside ~2 minutes earned a 429 that lasted at least 10 minutes.
Treat it as a low-volume lane (one fetch per handle per cool-off), never a
scaling path, and always surface `blocked.ratelimit` instead of retrying.
