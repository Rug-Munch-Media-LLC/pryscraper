"""Tests for commerce platform sync."""

from commerce_sync import sync_to_shopify, sync_to_woocommerce


def test_sync_woocommerce_no_creds() -> None:
    import asyncio

    result = asyncio.run(sync_to_woocommerce([{"name": "Test"}], "", "", ""))
    assert result["success"] is False
    assert result["total"] == 1
    assert result["synced"] == 0


def test_sync_shopify_no_creds() -> None:
    import asyncio

    result = asyncio.run(sync_to_shopify([{"name": "Test"}], "", ""))
    assert result["success"] is False
    assert result["total"] == 1
