# OSS CAPTCHA Solvers — definitive free-solver survey (2026-10)

**Status:** canonical survey · **Owner:** Pry engineering · **Companion:** `CAPTCHA-POLICY.md`
**Rule:** anything paid is eliminated. The free replacement must be best-in-class, or we do not ship it.
**Facts verified 2026-10-26** against the GitHub REST API (`stargazers_count`, `license.spdx_id`,
`pushed_at`, `language`) plus each repo's own README/LICENSE. Anything not checked that way is
marked `[UNVERIFIED]`.

## 0. Ground truth in this repo

`src/pry/engine/captcha/` (17 files, 1438 lines) still carries paid rungs — `CAPSOLVER_API_KEY`,
`CAPSOLVER_CREATE_URL`, `CAPSOLVER_RESULT_URL`, `2CAPTCHA_API_KEY` in `keys.py`, `submit.py`,
`token_api.py`. The captcha secrets file those keys are read from has never been provisioned on
this host (re-read 2026-10-26, absent), so those lanes report `no_key` and have never executed in
production. Eliminating them is a docs + ladder change, not a capability loss.

## 1. Matrix — what actually exists, verified

| Repo | ★ | Licence | Last commit | Lang | Class it solves | Verdict |
|---|---|---|---|---|---|---|
| [sarperavci/CloudflareBypassForScraping](https://github.com/sarperavci/CloudflareBypassForScraping) | 2626 | MIT | 2026-10-25 | Python | Turnstile widget/interstitial via a real Brave browser + DrissionPage, per-request proxies, `/fetch` endpoint | **adopt (service)** |
| [kaliiiiiiiiii-Vinyzu/patchright-python](https://github.com/kaliiiiiiiiii-Vinyzu/patchright-python) | 1581 | Apache-2.0 | 2026-10-20 | Python | stealth substrate; keeps the Playwright API, patches the CDP-visible tells | **adopt (core substrate)** |
| [daijro/camoufox](https://github.com/daijro/camoufox) | 12803 | MPL-2.0 | 2026-10-25 | Python | anti-detect Firefox (C++-level fingerprint patching), Turnstile-capable | **adopt (second substrate)** |
| [lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi) | 6777 | MIT | 2026-10-26 | Python | TLS/JA3+HTTP2 impersonation; avoids the challenge entirely | **adopt (tier 0)** |
| [seleniumbase/SeleniumBase](https://github.com/seleniumbase/SeleniumBase) | 13170 | MIT | 2026-10-25 | Python | UC/CDP mode with documented `uc_gui_click_captcha` | **adopt (alt substrate)** |
| [QIN2DIM/hcaptcha-challenger](https://github.com/QIN2DIM/hcaptcha-challenger) | 2562 | GPL-3.0 | 2026-08-15 | Python | hCaptcha `image_label_binary` (ResNet ONNX), `area_select` point (YOLOv8 ONNX), multiple-choice | **adopt as separate process** (GPL) |
| [sml2h3/ddddocr](https://github.com/sml2h3/ddddocr) | 14870 | MIT | 2026-03-10 | Python | classic image/text captcha OCR, ONNX, offline, small wheel | **adopt** |
| [tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) | 77171 | Apache-2.0 | 2026-10-24 | C++ | clean-font text captcha; weak on distortion | keep (already wired) |
| [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 91690 | Apache-2.0 | 2026-09-16 | Python | text detection+recognition; heavy install | optional tier-2 |
| [microsoft/unilm · TrOCR](https://github.com/microsoft/unilm) | 22237 | MIT | 2026-09-21 | Python | transformer OCR on clean printed text | optional, not a captcha specialist |
| [openai/whisper](https://github.com/openai/whisper) | 111288 | MIT | 2026-08-31 | Python | reCAPTCHA/hCaptcha **audio** path ASR | reference impl |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 26153 | MIT | 2026-10-25 | Python | same, CTranslate2 int8, much faster on CPU | **adopt (audio tier)** |
| [dessant/buster](https://github.com/dessant/buster) | 9354 | GPL-3.0 | 2026-06-27 | JS | human-in-the-loop audio solver extension | reference only |
| [ultrafunkamsterdam/undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) | 12887 | GPL-3.0 | 2025-07-05 | Python | stealth substrate; unmaintained since mid-2025 | **do not adopt** |
| [ultrafunkamsterdam/nodriver](https://github.com/ultrafunkamsterdam/nodriver) | 4890 | **AGPL-3.0** | 2026-10-08 | Python | CDP stealth, fast | **do not adopt** (AGPL) |
| [kaliiiiiiiiii-Vinyzu/patchright](https://github.com/kaliiiiiiiiii-Vinyzu/patchright) | 4982 | Apache-2.0 | 2026-10-25 | TypeScript | JS half of patchright | n/a (Python shop) |
| [Theyka/Turnstile-Solver](https://github.com/Theyka/Turnstile-Solver) | 955 | **CC-BY-NC-4.0** | 2025-08-02 | Python | Turnstile via patchright, threaded + HTTP API | **do not adopt** (non-commercial) |
| [omkarcloud/botasaurus](https://github.com/omkarcloud/botasaurus) | 5800 | MIT | 2026-07-26 | Python | all-in-one scraper framework w/ anti-detect | optional, framework-sized |
| [NopeCHALLC/nopecha-extension](https://github.com/NopeCHALLC/nopecha-extension) | 11061 | MIT | 2026-10-02 | JS | extension that **calls the paid NopeCHA service** | **excluded — paid** |
| [kerlomz/captcha_trainer](https://github.com/kerlomz/captcha_trainer) | 3218 | Apache-2.0 | 2025-11-09 | Python | train CNN+CTC models for classic captchas | only for a bespoke target |
| [nladuo/captcha-break](https://github.com/nladuo/captcha-break) | 727 | MIT | 2018-11-06 | C++ | OpenCV+tesseract classic captcha | stale |
| [ptigas/simple-captcha-solver](https://github.com/ptigas/simple-captcha-solver) | 601 | MIT | 2018-01-04 | Python | toy OpenCV segmentation | stale |
| [microsoft/playwright](https://github.com/microsoft/playwright) | 98539 | Apache-2.0 | 2026-10-25 | TS | baseline (detectable fingerprints) | baseline only |

## 2. Elimination table — paid lane → free replacement, with the honest gap

| Paid lane (current key) | Free replacement | Gap |
|---|---|---|
| `capsolver` — reCAPTCHA v2 **token** | **Audio path**: a stealth browser opens the audio challenge, the clip is fetched and transcribed by `faster-whisper` int8, the answer is typed back. No key, no third party. | Audio is rate-limited per IP/session; single-pass accuracy is not yet measured on our lanes `[UNVERIFIED]`. 5-15 s per clip. |
| `capsolver` — reCAPTCHA v2 **image grid** | `hcaptcha-challenger`'s detectors are hCaptcha-trained; **no equal free reCAPTCHA-grid model exists**. Best free attempt is a fine-tune on our own captures (`captcha_trainer`) or a local VLM. | **No free equivalent that is best-in-class — typed refusal** (`blocked.captcha_unsolved`). |
| `capsolver` — reCAPTCHA **v3 / enterprise score** | None. It is a reputation score, not a puzzle. | **No free equivalent — typed refusal.** Be clean: residential egress, real UA, human cadence, no headless. |
| `capsolver` / `2captcha` — hCaptcha **token** | `hcaptcha-challenger` (YOLOv8 point-select + ResNet binary, local ONNX, no key) | GPL-3.0 → separate process only. Cloudflare-fronted hCaptcha often wants the accessibility cookie; that flow is free but cookie-bearing. |
| `capsolver` / `2captcha` — **Turnstile** | `cloudflare-bypass` (Brave + DrissionPage), `patchright`, `camoufox`, SeleniumBase UC — click the checkbox inside the shadow DOM with real mouse events. | **Managed challenge / interstitial with no widget: no free equivalent — typed refusal.** Solve rate is IP-reputation-bound, not code-bound. |
| `2captcha` — hCaptcha **accessibility cookie** | The accessibility flow itself is free (email + cookie). | Needs a mailbox and a manual cookie bootstrap; we do **not** auto-register accounts. Disqualified as automation. |
| `anticaptcha`, `nopecha`, `deathbycaptcha`, `capmonster` | — | **Excluded, paid.** Never wire a key. |
| any LLM-vision solver (hosted grid answers) | Local only: `[UNVERIFIED]` whether a small local VLM reaches usable grid accuracy on our CPU lanes. | A paid API is disqualified by the operator rule. Do not adopt until measured locally. |

## 3. Recommended tier order per class

1. **Turnstile / CF interstitial** — (0) `curl_cffi` impersonation with no browser; (1) the
   existing `flaresolverr` lane; (2) `patchright` + real-mouse shadow-DOM click; (3) `camoufox`;
   (4) `cloudflare-bypass` as a service. Managed challenge → refuse.
2. **reCAPTCHA v2** — (1) audio: `patchright` → `faster-whisper` int8; (2) interactive checkbox
   with human mouse entropy, then audio; (3) image grid: refuse unless a local model is measured.
   Never the v2 token API.
3. **reCAPTCHA v3 / enterprise** — no solver. Score hygiene only; refuse on `blocked`.
4. **hCaptcha** — (1) `hcaptcha-challenger` in its own process (ONNX, offline); (2) an
   operator-supplied accessibility cookie; (3) refuse.
5. **Text / image OCR** — (0) `ddddocr` (MIT, ONNX, offline, best per-MB); (1) `tesseract` through
   the existing `preprocess_image`; (2) `PaddleOCR` for dense/noisy; (3) `captcha_trainer` only for
   a bespoke repeated target.
6. **Slider / rotate / puzzle** — no vetted free repo surfaced in this survey `[UNVERIFIED]`. The
   honest path is OpenCV template matching with our own gap measurement, and it is target-specific.
   Do not ship a generic claim.
7. **Substrate** — `curl_cffi` → `patchright` → `camoufox` → SeleniumBase UC. Nothing below.

## 4. Do not adopt

| Item | Reason |
|---|---|
| `Theyka/Turnstile-Solver` | **CC BY-NC 4.0** — non-commercial; unusable in a shipped product, and no commit since 2025-08-02. |
| `ultrafunkamsterdam/nodriver` | **AGPL-3.0** — network copyleft; serving it is a distribution trigger. |
| `undetected-chromedriver` | GPL-3.0 **and** unmaintained since 2025-07-05; breaks on current Chrome. Superseded by patchright. |
| `nopecha-extension` | MIT code, but every solve is a **paid API call** — excluded by rule. |
| `Buster` | Human-in-the-loop by design; not automatable, GPL-3.0. |
| `capsolver` / `2captcha` / `anticaptcha` / `deathbycaptcha` / `capmonster` | Paid. The keys referenced by `keys.py`, `submit.py`, `token_api.py` are dead lanes. |
| Any solver needing a phone number, a logged-in account, or a paid key | Disqualified on the operator rule, regardless of accuracy. |
| `nladuo/captcha-break`, `ptigas/simple-captcha-solver` | 2018 code, no maintenance, worse than `ddddocr` on every axis. |

## 5. Licence rule for wiring

MIT / Apache-2.0 / MPL-2.0 / BSD → in-process OK (MPL is file-level: keep notices).
GPL-3.0 / AGPL-3.0 → **separate process, HTTP boundary, no vendoring**; AGPL additionally needs a
source-offer review before we expose it.
CC-BY-NC → **never**.
A solver that needs a paid key, a phone number or a logged-in account is disqualified before
accuracy is even measured.

## 6. Per-class evidence notes (what the repo itself claims, not our hope)

| Class | What the code actually does | Confidence |
|---|---|---|
| Turnstile | `CloudflareBypassForScraping` clicks the checkbox inside the widget's shadow DOM and manages a browser pool with per-request proxies; `patchright` keeps the Playwright API while removing CDP tells; Camoufox patches at the C++ level. | **high** — three independent active projects, latest commit within 4 days of this survey. |
| hCaptcha image | `hcaptcha-challenger` ships local ONNX weights: ResNet binary classifier, YOLOv8 point detection, YOLOv8 segmentation for boxes. The README's own capability table marks box-select as unsupported. | **high** for binary/point; **box-select unsupported**. |
| reCAPTCHA audio | `faster-whisper` is a CTranslate2 port of Whisper, int8 on CPU, no network, MIT. Whisper is trained on noisy speech, which is the audio-challenge distribution. | **medium** — model is right, our *plumbing* (audio-switch click, clip URL, answer box) is not built yet. |
| Text/image OCR | `ddddocr` is a single ONNX wheel built for exactly this class; Tesseract is strongest on clean fonts; PaddleOCR adds detection for multi-line. | **high**. |
| reCAPTCHA v3 | Nothing in any surveyed repo produces a score. | **none — refuse**. |
| Slider/rotate | Nothing vetted. | **none — do not claim**. |

## 7. Decision record

- **Do not wire** any paid key. The four constants in `keys.py` / `submit.py` / `token_api.py` are
  to be marked dead lanes and the `no_key` outcome kept as an honest diagnostic.
- **Do not claim** a class we cannot solve: `blocked.captcha_unsolved` is a correct answer.
- **Do not vendor** copyleft. GPL/AGPL solvers run behind a process boundary or not at all.
- **Do re-verify** this table before adoption: a row older than a quarter is a guess.

```
curl -s https://api.github.com/repos/<owner>/<repo> \
  | jq -r '[.stargazers_count, .license.spdx_id, .pushed_at, .language] | @tsv'
curl -s https://raw.githubusercontent.com/<owner>/<repo>/main/LICENSE | head -3
```

Every `[UNVERIFIED]` above is a measurement we owe, not a claim we may repeat.
