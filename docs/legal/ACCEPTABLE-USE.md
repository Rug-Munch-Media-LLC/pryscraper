# Acceptable Use Policy — Pry

**Status:** draft for legal review · **Applies to:** hosted Pry API, MCP server, CLI, and SDK
**Owner:** Rug Munch Media LLC · **Contact:** abuse@rugmunch.io `[CONFIRM]`

This policy describes what Pry may be used for and what it may not. It is written
against the controls that exist in this repository. Where a control is planned but
not implemented, it is marked `[ROADMAP]`; it is not presented as live.

## 1. Permitted use

You may use Pry to:

- collect publicly accessible web content (pages reachable without authentication);
- extract structured data for research, monitoring, indexing, and analysis;
- operate the software yourself under the MIT licence (see `LICENSE`), subject to
  the law and the target site's terms;
- process data you are lawfully entitled to process, including personal data where
  you have a lawful basis as controller.

## 2. Prohibited use

You must not use Pry to:

1. **Bypass authentication.** No scraping behind a login wall, paywall, or account
   gate, and no use of credentials you do not own. This is a policy rule; automated
   login-wall detection is `[ROADMAP]`. Reports are handled through the block list
   in §5.
2. **Farm CAPTCHAs.** No integration with CAPTCHA-solving services and no
   human-click farms. Pry detects challenge pages (`src/pry/engine/block_detection.py`)
   so it can back off; it does not solve them. Adding a solver is a prohibited
   modification.
3. **Evade technical access controls** — no forging a `User-Agent` to impersonate a
   browser you are not, no circumvention of IP blocks, no credential stuffing, no
   exploitation of vulnerabilities.
4. **Disregard `robots.txt` or per-domain rate limits.** See §3.
5. **Process special-category or sensitive data** — health, biometric, genetic,
   sexual orientation, trade-union, political, religious data; government identifiers;
   full payment-card numbers; or children's data. The sensitive-data classifier in
   `compliance/gdpr.py` flags likely categories so callers can drop the record.
6. **Target sanctioned parties or jurisdictions.** You must not use Pry against
   entities subject to sanctions you are bound by. Automated sanctions screening is
   `[ROADMAP]`; today this is a contractual obligation on the customer.
7. **Build a competing copy of a target site's proprietary database** in violation of
   that site's terms, or redistribute scraped content in breach of copyright.
8. **Send unsolicited bulk messages** using data collected with Pry.
9. **Overload a target** — no unbounded concurrency, no deliberate request floods,
   no denial-of-service testing.

## 3. robots.txt and per-domain expectations

`compliance/policy.py` fetches and parses `robots.txt` (`check_robots_txt`), returning
`crawl_allowed`, `crawl_delay`, and `disallowed_paths`. The compliance report surfaces
these to the caller.

**Customer obligations:**

- honour `Disallow` for paths you request;
- honour `Crawl-delay` where published;
- identify your crawler honestly where the target requires it;
- stop when a target returns `429` or an anti-bot challenge, and back off.

**Engine behaviour (implemented):** retry tiers use bounded exponential backoff —
base delay 0.5–2.0s, capped at 5–10s, with 1–2 retries per tier
(`src/pry/engine/tier_retry_policy.py`). A detected challenge or rate-limit response
routes to backoff rather than an immediate retry.

**`[ROADMAP]`** A universal pre-fetch hard gate that refuses a request when
`crawl_allowed=false`, plus a global per-host concurrency semaphore. Today robots
results are advisory to the caller; enforcement rests on this policy and the block
list.

## 4. API rate expectations

Per-key limits are enforced in `src/pry/core/middleware_ratelimit.py` using the tier
defaults in `src/pry/core/api_keys_service.py`:

| Tier | Requests/minute | Monthly quota |
|---|---|---|
| FREE | 60 | 10,000 |
| PRO | 600 | 500,000 |
| ENTERPRISE | 6,000 | 10,000,000 |

Exceeding a limit returns `429`. Repeated or deliberate overrun is grounds for
suspension under §5. These are inbound API limits; they do not entitle a customer to
send that volume at a single third-party host.

## 5. Enforcement and suspension

Pry applies these controls, in order:

1. **Domain block (HTTP 451).** A host placed in the `domain_blocks` table is refused
   *before any fetch* — `src/pry/api/routers/scraping/scraping.py` raises
   `451 Domain blocked for compliance reasons`, and the check is shared with the
   scraper via `src/pry/core/domain_blocks.py`.
2. **Key suspension / revocation.** Keys are stored hashed (SHA-256) and can be
   revoked without recovering the plaintext (`src/pry/core/api_keys_service.py`).
3. **Audit trail.** Security-relevant events are written to the `audit_events` table
   by `src/pry/core/audit.py` (model at
   `src/pry/core/db/models_auth.py`) and to the compliance JSONL audit log
   (`src/pry/compliance/gdpr.py`).

**Suspension criteria:** a credible abuse report; a sanctions or law-enforcement
request; repeated disregard of `robots.txt` or `429`/`451` responses; attempts to
bypass authentication or solve challenges; or processing of prohibited data
categories. Suspension may be immediate where continued access would cause harm.

## 6. Client IP and proxy trust

Pry derives the client address from the socket peer. A forwarding header is trusted
only when the peer is loopback or listed in `PRY_TRUSTED_PROXIES` (comma/space
separated IPs or CIDRs) — see `src/pry/core/middleware.py` and
`src/pry/core/middleware_auth.py`. Misconfiguring this variable weakens rate-limit
and audit attribution; operators must keep it to their own ingress only.

## 7. Reporting abuse

Email **abuse@rugmunch.io** `[CONFIRM]` with the domain, the offending request
pattern, and timestamps. We aim to acknowledge within **2 business days** `[TARGET]`
and to place a validated block within **5 business days** `[TARGET]`.

## 8. Changes

This policy may be updated. Material changes are published in the repository; for
hosted customers, notification is `[ROADMAP]` — no automated notification exists today.
