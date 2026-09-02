# CAPTCHA Solving

Pry ships a modular CAPTCHA solver registry in `src/pry/captcha/` with
automatic fallback across solver backends.

## Supported CAPTCHA types

| Type | Module |
|------|--------|
| reCAPTCHA v2 | `captcha/recaptcha_v2` |
| reCAPTCHA v3 | `captcha/recaptcha_v3` |
| hCaptcha | `captcha/hcaptcha` |
| Cloudflare Turnstile | `captcha/turnstile` |
| Image / OCR | `captcha/image_ocr` |

## Solver backends (tried in order)

1. **2captcha-compatible** — `PRY_CAPTCHA_2CAPTCHA_API_KEY` (also works with
   anti-captcha / capmonster style keys)
2. **Capsolver** — `PRY_CAPTCHA_CAPSOLVER_API_KEY` (tried after 2captcha)
3. **Local OCR** — `PRY_CAPTCHA_OCR_BACKEND` = `tesseract` (default) /
   `easyocr` / `auto`

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `PRY_CAPTCHA_ENABLED` | `true` | Master toggle |
| `PRY_CAPTCHA_2CAPTCHA_API_KEY` | unset | 2captcha-style API key |
| `PRY_CAPTCHA_CAPSOLVER_API_KEY` | unset | Capsolver key |
| `PRY_CAPTCHA_OCR_BACKEND` | `tesseract` | Local OCR backend |

When no external solver key is configured, Pry falls back to local OCR and
to the stealth browser tiers, which pass many challenges without an
explicit solver.

## Cost

CAPTCHA solving is not a standalone x402 operation — it is bundled into the
price of the scraping operation that triggered it (see
[x402 pricing](../x402/pricing)).
