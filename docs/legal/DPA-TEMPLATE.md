# Data Processing Agreement — Template

**Status:** template, not executed · **Last reviewed:** 2026-10-18
**Provider (processor):** Rug Munch Media LLC · **Contact:** security@rugmunch.io `[CONFIRM]`

> This is a template. It is not legal advice and has not been reviewed by counsel.
> Bracketed `[CONFIRM]` items must be completed before use. `[ROADMAP]` items are
> controls that do **not** exist yet and must not be represented as operating.

## 1. Roles

- **Controller:** the customer, which determines the purposes and means of processing.
- **Processor:** Rug Munch Media LLC, which processes personal data on the
  controller's documented instructions to provide Pry.
- Where a customer uses Pry to scrape third-party sites, the customer is controller
  for any personal data in the results; Rug Munch Media LLC does not determine those
  purposes.

## 2. Scope and subject matter

Processing consists of: fetching URLs supplied by the controller; extracting content;
storing job inputs/results, quality history, session metadata, and usage records;
and returning results through the API.

Data categories: URLs, page content (which may incidentally contain personal data),
API key identifiers, client IP addresses, and usage metadata. Special-category data
is out of scope and prohibited by the Acceptable Use Policy.

## 3. Processor obligations

1. Process only on documented instructions, including transfer restrictions.
2. Ensure personnel are bound by confidentiality.
3. Implement the security measures in §5.
4. Assist with data-subject requests using the erasure and retention facilities in §6.
5. Notify the controller of a personal-data breach without undue delay (§7).
6. Delete or return data at termination (§6.4).
7. Make available information necessary to demonstrate compliance, and allow audits
   `[CONFIRM: audit scope, frequency, cost]`.

## 4. Sub-processors

Sub-processors are listed in `SUB-PROCESSORS.md`. The controller gives general
authorisation for those categories `[CONFIRM]`. The processor will give notice of a
new sub-processor `[ROADMAP]` — there is no automated notification today — and the
controller may object `[CONFIRM: objection window]`.

## 5. Security measures

### 5.1 Measures that exist in the codebase

| Measure | Implementation |
|---|---|
| API keys stored hashed | SHA-256 digest, plaintext never persisted — `src/pry/core/api_keys_service.py` |
| Audit trail | `audit_events` table written by `src/pry/core/audit.py`; compliance JSONL in `src/pry/compliance/gdpr.py` |
| Access attribution | Client address derived from socket peer; forwarding headers trusted only from `PRY_TRUSTED_PROXIES` — `src/pry/core/middleware.py`, `src/pry/core/middleware_auth.py` |
| Rate limiting / abuse control | Per-key RPM and quota — `src/pry/core/middleware_ratelimit.py` |
| Erasure with pseudonymisation | `src/pry/compliance/deletion_logic.py` (deleted vs pseudonymised scopes, per-store manifest) |
| Retention sweep | `src/pry/compliance/gdpr.py` (`apply_retention_policy`) |
| Legal blocks | HTTP 451 on blocked hosts — `src/pry/core/domain_blocks.py`, `src/pry/api/routers/scraping/scraping.py` |
| Domain purge | `purge_domain(domain, dry_run=True)` — `src/pry/core/domain_blocks.py` |

### 5.2 `[ROADMAP]` — not implemented

- Encryption at rest for stored scrape results and database volumes.
- Field-level encryption or tokenisation of content that may contain personal data.
- Automated sub-processor change notification.
- Automated audit-log expiry (the retention value is documented, but no scheduled
  deletion job exists for `audit_events` or the JSONL audit files).
- Per-tenant data isolation guarantees beyond the current deployment model.
- Independent penetration test and any security certification.

**No certification or audit is claimed.** Rug Munch Media LLC does not hold SOC 2,
ISO 27001, or an equivalent attestation. Any statement to the contrary is incorrect.

## 6. Data-subject requests, return, and deletion

### 6.1 Erasure

`process_deletion(user_id)` deletes personal data and pseudonymises retained
financial records. It reports one of `completed`, `partial`, or
`no_matching_records`; `no_matching_records` is explicitly **not** proof of erasure.

| Store | Action |
|---|---|
| `gdpr/consent`, `quality`, `sessions` | deleted |
| `usage`, `scrape_jobs` | deleted |
| `ledger_entries`, `x402_payment_records`, `x402_settlement_records`, `referrals`, `hosting_invoices` | pseudonymised (financial retention) |
| `x402/jsonl` | deleted |

### 6.2 Timelines

| Action | Target |
|---|---|
| Acknowledge a data-subject request | 5 business days `[TARGET]` |
| Execute erasure after verification | 30 calendar days `[TARGET]` |
| Confirm outcome with the per-store manifest | with the erasure report |

These are operational targets, not contractual SLAs unless separately agreed
`[CONFIRM]`.

### 6.3 Retention

See `DATA-RETENTION.md`. Financial records subject to a statutory retention duty are
pseudonymised rather than deleted.

### 6.4 Termination

On termination the controller may request export `[CONFIRM: format, window]`; after
the export window the processor deletes controller data using the same erasure path,
subject to statutory retention. Financial records remain pseudonymised for the
retention period.

## 7. Breach notification

The processor notifies the controller **without undue delay and within 72 hours** of
becoming aware of a personal-data breach `[TARGET]`, including: nature of the breach,
categories and approximate volume of data and subjects, likely consequences, and
measures taken. This supports the controller's own obligation to notify a supervisory
authority within 72 hours where required.

Notification contact: security@rugmunch.io `[CONFIRM]`.
There is no automated breach-detection-to-notification pipeline `[ROADMAP]`; the
timeline depends on operator response.

## 8. International transfers

Hosting location and any transfer mechanism (e.g. SCCs) are `[CONFIRM]`. The
repository does not define a data-residency guarantee; deployments are
operator-controlled. A transfer impact assessment is `[ROADMAP]`.

## 9. Liability and term

`[CONFIRM: term, liability cap, governing law, indemnities]` — to be completed by
counsel. Nothing in this template limits rights that cannot be limited by law.
