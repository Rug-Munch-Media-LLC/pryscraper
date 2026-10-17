# Copyright / DMCA Takedown Procedure — Pry

**Status:** draft for legal review · **Agent:** Rug Munch Media LLC
**Designated contact:** abuse@rugmunch.io `[CONFIRM]` — a designated DMCA agent
registration with the U.S. Copyright Office is `[ROADMAP]`. Until that registration
is filed, this document is an operational procedure, not a statutory safe-harbour
claim.

Pry is a scraping tool. It does not host or publish third-party content as a service;
it stores fetched records on behalf of the operator/customer. A takedown therefore
usually resolves to (a) removing stored records for a domain, and (b) blocking the
domain from future fetches.

## 1. How to submit a notice

Send to **abuse@rugmunch.io** `[CONFIRM]` with subject line `DMCA NOTICE — <domain>`.
Postal address: `[CONFIRM]` — not yet published; do not invent one.

## 2. Required fields

A notice must include all of the following. Incomplete notices may be returned.

1. Identification of the copyrighted work claimed to be infringed (or a
   representative list, if multiple works at one site).
2. Identification of the material claimed to be infringing, with enough detail to
   locate it — at minimum the **domain**, and where possible the specific URLs.
3. Your name, organisation, mailing address, telephone number, and email address.
4. A statement that you have a good-faith belief the use is not authorised by the
   copyright owner, its agent, or the law.
5. A statement, under penalty of perjury, that the information is accurate and that
   you are the owner or authorised to act for the owner.
6. Your physical or electronic signature.

## 3. Handling process

Targets are operational, not contractual. `[TARGET]` marks are goals, not SLAs.

| Step | Action | Target |
|---|---|---|
| 1 | Acknowledge receipt | 2 business days `[TARGET]` |
| 2 | Triage: validate completeness and plausibility | 3 business days `[TARGET]` |
| 3 | Dry-run the purge to size the impact | 5 business days `[TARGET]` |
| 4 | Apply the domain block (451) and purge stored records | 5 business days `[TARGET]` |
| 5 | Confirm the outcome to the complainant | 10 business days `[TARGET]` |

### 3.1 Dry run, then apply

`purge_domain(domain, dry_run=True)` in `src/pry/core/domain_blocks.py` counts
matching records across the `quality` and `sessions` stores and the database
(`usage`, `scrape_jobs`). It never deletes on the default path.

```
POST /v1/gdpr/domain/purge
{ "domain": "example.com", "dry_run": true }    # count only (default)
{ "domain": "example.com", "dry_run": false }   # apply
```

The endpoint is defined in `src/pry/api/routers/integrations/gdpr.py`. **Always run
the dry run first and record its output**; a purge without a prior count cannot be
evidenced afterwards.

### 3.2 Block

Insert the host into the `domain_blocks` table
(`src/pry/core/domain_blocks.py`, `_DDL`). Once present, every scraping request to
that host is refused with **451** before any network fetch
(`src/pry/api/routers/scraping/scraping.py`). The block list is the enforcement point;
there is currently no admin HTTP endpoint for adding a block `[ROADMAP]`, so it is an
operator database action. Record the operator, timestamp, and reason.

## 4. Counter-notice

A customer or operator whose records were removed may submit a counter-notice to the
same address. It must include:

1. identification of the material removed and the location it appeared at;
2. a statement under penalty of perjury that the material was removed by mistake or
   misidentification, with a good-faith belief the use is lawful;
3. consent to the jurisdiction of a competent court `[CONFIRM jurisdiction]`;
4. name, address, telephone, email, and physical or electronic signature.

On receipt, the block may be lifted and records restored **only** where the original
complainant has been notified and the legal position permits it. Restoration is an
operator decision recorded in the audit log; there is no automated counter-notice
workflow `[ROADMAP]`.

## 5. Records

Each notice, dry-run output, block, and purge result is retained as a compliance
record. Audit events are written to `audit_events` via `src/pry/core/audit.py`.
Retention for these records is described in `DATA-RETENTION.md`.

## 6. Repeat infringers

A domain that receives repeated valid notices is placed on the permanent block list.
There is no automatic strike counter `[ROADMAP]`; the determination is made by the
operator on the evidence in the notice file.

## 7. Misrepresentation

Knowingly materially misrepresenting that material is infringing may expose the
complainant to liability. Notices are reviewed before a block is applied for this
reason.
