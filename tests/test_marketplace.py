"""Tests for marketplace, x402 middleware, and webhooks."""

import asyncio

from actor_marketplace import Actor, ActorMarketplace, ActorVisibility
from webhook_delivery import WebhookDelivery
from x402_middleware import PAID_ENDPOINTS, X402_PRICING


def test_x402_pricing() -> None:
    assert "scrape" in X402_PRICING
    assert X402_PRICING["scrape"]["price_usd"] > 0
    for info in X402_PRICING.values():
        assert "price_usd" in info
        assert "description" in info


def test_x402_paid_endpoints() -> None:
    assert "/v1/scrape" in PAID_ENDPOINTS
    assert "/v1/crawl" in PAID_ENDPOINTS
    assert len(PAID_ENDPOINTS) >= 5


def test_x402_middleware_signing() -> None:
    w = WebhookDelivery(signing_secret="test-secret")
    sig = w.sign_payload({"event": "test", "data": {"x": 1}})
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA-256 hex


def test_actor_marketplace_create() -> None:
    m = ActorMarketplace()
    actor = m.create("Test Actor", "Test description", template_id="amazon-product",
                     price_per_run=0.01, visibility=ActorVisibility.PRIVATE, tags=["e-commerce"])
    assert actor.name == "Test Actor"
    assert actor.template_id == "amazon-product"
    assert actor.price_per_run == 0.01
    assert "e-commerce" in actor.tags


def test_actor_marketplace_list() -> None:
    m = ActorMarketplace()
    m.create("Test 1", "Desc", tags=["test"])
    actors = m.list()
    assert len(actors) >= 1


def test_actor_marketplace_filter() -> None:
    m = ActorMarketplace()
    m.create("Public", "D", visibility=ActorVisibility.PUBLIC, tags=["free"])
    m.create("Private", "D", visibility=ActorVisibility.PRIVATE, tags=["private"])
    public = m.list(visibility="public")
    private = m.list(visibility="private")
    assert all(a["visibility"] == "public" for a in public)
    assert all(a["visibility"] == "private" for a in private)


def test_actor_marketplace_run_missing() -> None:
    m = ActorMarketplace()
    result = asyncio.run(m.run("nonexistent"))
    assert result["success"] is False


def test_actor_to_dict() -> None:
    a = Actor("id1", "Name", "Desc")
    d = a.to_dict()
    assert d["name"] == "Name"
    assert d["actor_id"] == "id1"
    assert "created_at" in d


def test_webhook_signature_consistency() -> None:
    w1 = WebhookDelivery(signing_secret="same-secret")
    w2 = WebhookDelivery(signing_secret="same-secret")
    payload = {"event": "test", "x": 1}
    assert w1.sign_payload(payload) == w2.sign_payload(payload)


def test_webhook_different_secrets() -> None:
    w1 = WebhookDelivery(signing_secret="secret1")
    w2 = WebhookDelivery(signing_secret="secret2")
    payload = {"event": "test"}
    assert w1.sign_payload(payload) != w2.sign_payload(payload)


def test_actor_visibility_enum() -> None:
    assert ActorVisibility.PRIVATE.value == "private"
    assert ActorVisibility.PUBLIC.value == "public"
    assert ActorVisibility.UNLISTED.value == "unlist"
