"""Billing lifecycle: invoice numbering, refunds, tax."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from pry.commerce.billing import invoices, refunds
from pry.core.db import models as models_mod
from tests.billing_support import (  # noqa: F401 — fixture for this module
    create_invoice,
    db,
)


def test_allocate_number_is_sequential_and_formatted(db: Path) -> None:
    first = invoices.allocate_invoice_number("202610")
    second = invoices.allocate_invoice_number("202610")
    assert (first, second) == ("INV-202610-000001", "INV-202610-000002")
    assert invoices.allocate_invoice_number("202611") == "INV-202611-000001"


def test_concurrent_allocation_yields_distinct_numbers(db: Path) -> None:
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(invoices.allocate_invoice_number("202612"))
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(set(results)) == 4, results


def test_assign_number_to_stored_invoice_is_idempotent(db: Path) -> None:
    create_invoice("inv_a", "u_num")
    first = invoices.assign_invoice_number("inv_a")
    assert (first.startswith("INV-"), first.endswith("000001")) == (True, True)
    assert invoices.assign_invoice_number("inv_a") == first


def test_refund_exceeding_paid_is_rejected(db: Path) -> None:
    create_invoice("inv_over", "u_ref", amount="50")
    with pytest.raises(refunds.RefundError, match="exceeds paid"):
        refunds.refund_invoice("inv_over", "50.01", "over")


def test_partial_refund_is_recorded_as_partial(db: Path) -> None:
    create_invoice("inv_part", "u_ref2", amount="100")
    first = refunds.refund_invoice("inv_part", "40", "goodwill")
    assert first["status"] == "partially_refunded"
    assert first["duplicate"] is False
    assert Decimal(str(first["refunded_amount"])) == Decimal("40")


def test_partial_refund_is_idempotent(db: Path) -> None:
    create_invoice("inv_part", "u_ref2", amount="100")
    first = refunds.refund_invoice("inv_part", "40", "goodwill")
    second = refunds.refund_invoice("inv_part", "40", "goodwill")
    assert second["duplicate"] is True
    assert second["refunded_amount"] == first["refunded_amount"]


def test_partial_refund_writes_a_single_ledger_entry(db: Path) -> None:
    from pry.core.db.session import get_session

    create_invoice("inv_part", "u_ref2", amount="100")
    refunds.refund_invoice("inv_part", "40", "goodwill")
    with get_session() as session:
        rows = session.query(models_mod.LedgerEntry).filter_by(reference="refund:inv_part").all()
        assert len(rows) == 1
        assert Decimal(str(rows[0].delta_usd)) == Decimal("-40")


def test_full_refund_marks_invoice_refunded(db: Path) -> None:
    create_invoice("inv_full", "u_ref3", amount="100")
    assert refunds.refund_invoice("inv_full", "100", "duplicate")["status"] == "refunded"


def test_tax_decimal_math() -> None:
    tax = invoices.compute_tax("100.10", "0.20", "de")
    assert tax["tax_amount"] == Decimal("20.020000")
    assert tax["total_usd"] == Decimal("120.120000")
    assert tax["tax_country"] == "DE"
    assert isinstance(tax["tax_amount"], Decimal)
    zero = invoices.compute_tax("99.99", "0.20", "IE", reverse_charge=True)
    assert (zero["tax_amount"], zero["total_usd"]) == (0, Decimal("99.990000"))
    with pytest.raises(ValueError, match="immutable"):
        invoices.apply_tax({"amount_usd": 10, "status": "paid"}, "0.2")
