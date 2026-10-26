# CAPTCHA Policy — solve when needed, refuse only robots and paid APIs

**Status:** canonical · **Owner:** Pry engineering · **Supersedes:** any
"opt-in / default-off" wording in older docs.

## Operating rule

1. **Solving is ON by default.** `PRY_CAPTCHA_ENABLED` defaults to `1`. When
   `pry.engine.block_detection.detect_block` classifies a response as a
   captcha or challenge (`captcha`, `cloudflare`, `js_required`), the ladder runs.
2. **We are willing to use any and all solver lanes** to get the content. The
   ladder tries every available lane in priority order until one succeeds.
3. **Two refusals remain — both ours, not policy choices:**
   - **`blocked.robots`** — a robots.txt-disallowed path is never solved, and
     the ladder makes **zero** solver attempts on it.
   - **`skipped.paid_api`** — a solver is never applied to a paid or
     logged-in API endpoint (API path prefixes, `api_key`/`access_token`-style
     query parameters). Solver credit and credentials are not spent there.
4. **Honest failure.** If every lane fails the result is
   `blocked.captcha_unsolved`, listing each attempt and the missing key env
   vars. Never a silent `None`.

## Priority ladder

| # | Lane                    | Cost        | Key required | What it handles |
|---|-------------------------|-------------|--------------|-----------------|
| 1 | `flaresolverr`          | free        | no           | JS / Cloudflare interstitials, returns settled HTML + cookies/UA |
| 2 | `image`                 | free (OCR)  | no           | classic image CAPTCHAs (Tesseract / EasyOCR) |
| 3 | `capsolver`             | paid        | `PRY_CAPTCHA_CAPSOLVER_API_KEY` | reCAPTCHA v2/v3, hCaptcha, Turnstile |
| 4 | `2captcha`              | paid        | `PRY_CAPTCHA_2CAPTCHA_API_KEY`  | same as above |
| 5 | `token` (registry)      | paid        | any token key | provider registry fallback for the detected widget type |

Order is **free lanes first**; paid lanes only run when their key is present.
The whole run is capped by `PRY_CAPTCHA_MAX_SECONDS` (default **60 s**); each
attempt emits exactly one line:

```
captcha_attempt provider=<lane> type=<kind> ms=<n> outcome=<solved|unsolved|no_key|no_input|not_applicable|timeout|deadline>
```

A `flaresolverr` response that still contains challenge markers
(`g-recaptcha`, `cf-turnstile`, `just a moment`, `verify you are human`, …) is
**not** a solve.

## Keys — file first, env last

Provision in the file named by **`PRY_CAPTCHA_ENV_FILE`** (mode 600), not in code.
The fleet points that variable at its secrets directory; the default is
`/etc/pry/captcha.env`:

```ini
PRY_CAPTCHA_CAPSOLVER_API_KEY=<key>
PRY_CAPTCHA_2CAPTCHA_API_KEY=<key>
```

`load_captcha_keys()` reads that file first, then the process environment, and
only fills settings fields that are still empty. A key added to the file is
used on the next process start — **no code change**. Override the path with
`PRY_CAPTCHA_ENV_FILE`.

Inspect the current state:

```bash
make captcha-keys     # provisioning instructions
make captcha-doctor   # ladder order, missing keys, FlareSolverr health
```

`captcha_diagnostics()` reports `token_providers_unavailable` with the exact
env var names; the same warning is logged at package import (startup). Missing
keys are loud; the free lanes keep working.

## What "solved" means

A solved token is submitted back with `submit_solution(url, token)` (form field
`g-recaptcha-response` by default). A token that is never submitted is not a
result.

## Verification

`tests/test_captcha_ladder.py` proves the three required behaviours:

1. no key + real captcha page → `flaresolverr` and `image` attempted, then
   `blocked.captcha_unsolved` naming both missing keys;
2. mocked token key → correct capsolver request shape and the solved token is
   posted to the page;
3. robots-disallowed URL → `blocked.robots` with zero solver attempts.
