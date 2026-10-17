"""Operator SQL for reconciling booked vs settled x402 revenue."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

REVENUE_RECONCILIATION_SQL = """
CREATE OR REPLACE VIEW revenue_reconciliation AS
SELECT
    p.payment_id,
    p.tx_hash,
    p.network,
    p.asset,
    p.amount_usd,
    p.verified,
    COALESCE(p.verified_at, p.created_at) AS booked_at,
    s.settled_at,
    s.amount_usd AS settled_usd,
    CASE
        WHEN p.verified AND s.settled_at IS NOT NULL THEN $$settled$$
        WHEN p.verified THEN $$verified_unsettled$$
        ELSE $$unverified$$
    END AS reconciliation_state
FROM x402_payment_records AS p
LEFT JOIN x402_settlement_records AS s
       ON s.payment_id = p.payment_id
      AND s.tx_hash = p.tx_hash;
"""

#: The three operator queries the reconciliation view exists to answer.
REVENUE_RECONCILIATION_QUERIES = {
    # 1. Verified revenue by day (never trust an unverified row as income).
    "revenue_by_day": """
SELECT date_trunc($$day$$, COALESCE(verified_at, created_at)) AS day,
       COUNT(*) AS payments,
       ROUND(SUM(amount_usd)::numeric, 6) AS revenue_usd
FROM x402_payment_records
WHERE verified
GROUP BY 1
ORDER BY 1 DESC;
""",
    # 2. Verified but unsettled after 24h = money that never moved.
    "verified_but_unsettled": """
SELECT p.payment_id, p.tx_hash, p.amount_usd, p.verified_at
FROM x402_payment_records AS p
LEFT JOIN x402_settlement_records AS s
       ON s.payment_id = p.payment_id
      AND s.tx_hash = p.tx_hash
WHERE p.verified
  AND s.settled_at IS NULL
  AND COALESCE(p.verified_at, p.created_at) < now() - interval $$24 hours$$
ORDER BY p.verified_at NULLS LAST;
""",
    # 3. Payment amount vs settled amount drift (should be exact).
    "amount_mismatches": """
SELECT p.payment_id, p.tx_hash, p.amount_usd, s.amount_usd AS settled_usd
FROM x402_payment_records AS p
JOIN x402_settlement_records AS s
  ON s.payment_id = p.payment_id
 AND s.tx_hash = p.tx_hash
WHERE p.verified
  AND ABS(COALESCE(p.amount_usd, 0) - COALESCE(s.amount_usd, 0)) > 0.000001;
""",
}
