# Auto-Signup

Pry includes an auto-signup automation module (`src/pry/signup/`) that can
register accounts on target sites on your behalf: form detection, a signup
engine, and email verification handling.

## What it does

- **Form detection** — locates registration forms on a target page and
  infers field semantics (email, password, username, captcha).
- **Signup engine** — fills and submits the form through the stealth
  browser tiers, reusing the same anti-detection stack as scraping.
- **Email verification** — completes verify-email link flows; the
  email-verify link route is treated as a free pre-auth human surface.

## How to use it

### REST

```bash
curl -X POST http://localhost:8002/v1/automate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/register", "action": "signup"}'
```

`/v1/automate` is the x402-gated `browser_automation` operation —
**$0.05/call** (see [x402 pricing](../x402/pricing)).

### MCP

Browser automation is exposed through the MCP tool surface; use
`pry_scrape` with browser tiers or the automation endpoint for full
signup flows.

## Compliance

Auto-signup is intended for accounts you are authorized to create. Always
check `pry_compliance` before automating registration on a third-party
site, and respect the target's terms of service.
