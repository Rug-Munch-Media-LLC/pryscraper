# Stealth

Pry's stealth layer lives in `src/pry/engine/stealth_engine.py` and the
`stealth_scripts/` JS bundle. It is applied automatically by the
[15-tier fallback chain](15-tier-fallback) — no configuration needed for the
common case.

## What runs automatically

- **Browser fingerprint hardening** — `webdriver_hide`, `canvas_noise`,
  `webgl_noise`, and `audio_noise` scripts are injected into every
  Playwright/undetected-chromedriver session.
- **Human behavior emulation** — `human_mouse` and `human_type` scripts
  produce realistic pointer paths and keystroke timing.
- **Rotating user agents** — a curated Chrome/Firefox UA pool rotates per
  request at the HTTP tier.
- **TLS fingerprint impersonation** — curl_cffi JA3/JA4 impersonation at
  tier 2 defeats TLS-level bot detection before a browser is ever launched.
- **Cookie warming** — pre-warmed cookie jars (`warmed_cookies/`) let
  repeat visits to a domain start from an established session.
- **Camoufox** — source-level anti-fingerprinting Firefox (tier 6) when
  Chromium-based stealth is not enough.

## Per-domain adaptation

The resilience layer (`src/pry/engine/resilience.py`) remembers which tiers
succeed per domain and promotes proven tiers to the front of the chain,
while chronically failing tiers are skipped for 5 minutes. Each domain
converges on the cheapest stealth profile that works.

## Related env vars

See the [Deployment guide](https://codeberg.org/RugMunchMedia/pryscraper)
(`docs/ops/DEPLOYMENT.md` in the repo) for proxy and browser configuration.
