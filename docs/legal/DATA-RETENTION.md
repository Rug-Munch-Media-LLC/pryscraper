# Data Retention Schedule — Pry

**Status:** draft for legal review · **Last updated:** 2026-10-18
**Sources of truth:** `src/pry/compliance/deletion_logic.py` (erasure scope) and
`src/pry/compliance/gdpr.py` (retention policy + sweep).

Values below are what the code states or implements. Where a documented value has no
enforcement mechanism, that is called out rather than implied.

| Table / store | Retention | Legal basis | Mechanism |
|---|---|---|---|
| `gdpr/consent` (JSON) | 365 days from consent | Art. 6(1)(a); expires with consent | `expires_at` checked by `apply_retention_policy`; erased on request |
| `quality` history (JSON) | 90 days | Art. 6(1)(f) operational quality | Age-based sweep (`_remove_expired`, 90d); erased on request |
| `sessions` metadata (JSON) | 30 days | Art. 6(1)(f) operational | Documented in `get_retention_policy`; erased on request. Age-based sweep for this store is `[ROADMAP]` |
| `freshness` / fingerprints | 30 days | Art. 6(1)(f) cache freshness | Age-based sweep (`_remove_expired`, 30d) |
| `monitor_snapshots` | 90 days | Art. 6(1)(f) monitoring | Documented only; no sweep implemented `[ROADMAP]` |
| `audit_logs` (JSONL) | 365 days | Art. 6(1)(c)/(f) security accountability | Documented only; no automated expiry `[ROADMAP]` |
| `audit_events` (DB) | 365 days | Art. 6(1)(c)/(f) security accountability | Documented only; no purge job `[ROADMAP]` |
| `usage` | No fixed TTL | Art. 6(1)(b)/(f) billing and abuse | Deleted on erasure; no scheduled expiry `[ROADMAP]` |
| `scrape_jobs` (inputs/results) | No fixed TTL | Art. 6(1)(b) service delivery | Deleted on erasure; customer-triggered or domain purge; no scheduled expiry `[ROADMAP]` |
| `domain_blocks` | Indefinite | Art. 6(1)(c) legal compliance | Persistent block list; domain + reason + created_at only |
| `ledger_entries` | 7 years `[CONFIRM]` | Art. 17(3)(b); tax/accounting law | **Pseudonymised** on erasure, not deleted |
| `x402_payment_records` | 7 years `[CONFIRM]` | Art. 17(3)(b); financial records | **Pseudonymised** on erasure |
| `x402_settlement_records` | 7 years `[CONFIRM]` | Art. 17(3)(b); settlement records | **Pseudonymised** on erasure |
| `referrals` | 7 years `[CONFIRM]` | Art. 17(3)(b); revenue accounting | **Pseudonymised** on erasure |
| `hosting_invoices` | 7 years `[CONFIRM]` | Art. 17(3)(b); invoice/tax retention | **Pseudonymised** on erasure |
| `x402/jsonl` ledger lines | No fixed TTL | Art. 6(1)(b) | Deleted on erasure |

## Notes

- **7 years** is the accounting-retention figure used for the financial stores. The
  exact period is jurisdiction-dependent and must be confirmed per entity before this
  schedule is published `[CONFIRM]`.
- **Pseudonymisation, not deletion.** Financial rows keep the accounting record but
  lose the direct identifier; the erasure report counts these separately as
  `pseudonymised_records`.
- **Erasure is not a retention policy.** `process_deletion` returns
  `no_matching_records` when nothing matched, which is not evidence that no data
  exists. A `partial` result means at least one store was unreadable and must be
  re-run.
- **Domain purge** (`purge_domain`, dry-run by default) removes stored records for a
  whole domain across `quality`, `sessions`, `usage`, and `scrape_jobs`; it is not a
  data-subject erasure and does not touch financial stores.
- **Backups** are not covered by any in-code mechanism; backup retention and
  restoration-time deletion are `[ROADMAP]` and must be documented per deployment
  `[CONFIRM]`.
