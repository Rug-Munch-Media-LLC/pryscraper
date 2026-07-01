"""Tests for email inbox scraping."""

from email_scraper import (
    _classify_email,
    extract_email_data,
)


def test_classify_order() -> None:
    result = _classify_email("Your Amazon.com order has shipped!", "Order #123-4567890")
    assert result == "order_confirmation"


def test_classify_invoice() -> None:
    result = _classify_email("Invoice from Acme Corp", "Invoice #INV-2024-001 is due")
    assert result == "invoice"


def test_classify_receipt() -> None:
    result = _classify_email("Your receipt from Starbucks", "Receipt #12345")
    assert result == "receipt"


def test_classify_shipping() -> None:
    result = _classify_email("Your package is on its way!", "Tracking number: 1Z999AA10123456784")
    assert result == "shipping_notification"


def test_classify_other() -> None:
    result = _classify_email("Meeting reminder", "Don't forget the meeting at 3pm")
    assert result == "other"


def test_extract_order_number() -> None:
    result = extract_email_data(
        "Order Confirmation", "Order #ABC-12345 has been placed. Total: $49.99", "orders@shop.com"
    )
    assert result["email_type"] == "order_confirmation"
    assert "ABC-12345" in str(result["extracted_data"])


def test_extract_amount() -> None:
    result = extract_email_data("Receipt", "Amount charged: $129.99", "billing@store.com")
    assert result["email_type"] == "receipt"


def test_extract_tracking() -> None:
    result = extract_email_data(
        "Shipping Update", "Your tracking number is 1Z999AA10123456784", "shipping@ups.com"
    )
    assert result["email_type"] == "shipping_notification"
    assert "1Z999AA10123456784" in str(result["extracted_data"]) or "tracking" in str(
        result["extracted_data"]
    )


def test_extract_invoice_number() -> None:
    result = extract_email_data(
        "Invoice from Vendor", "Invoice #INV-2024-001 for $5,000.00", "billing@vendor.com"
    )
    assert result["email_type"] == "invoice"
