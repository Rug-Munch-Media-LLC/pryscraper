"""Tests for Pry SDK classes."""

from pry_sdk import PryCrawl, PryCrawlSync


def test_prycrawl_init() -> None:
    mc = PryCrawl("http://localhost:8002")
    assert mc.base_url == "http://localhost:8002"
    assert mc.timeout == 60


def test_prycrawl_init_with_key() -> None:
    mc = PryCrawl("http://localhost:8002", api_key="test-key")
    assert mc._headers["Authorization"] == "Bearer test-key"


def test_prycrawl_init_strips_trailing_slash() -> None:
    mc = PryCrawl("http://localhost:8002/")
    assert mc.base_url == "http://localhost:8002"


def test_prycrawlsync_init() -> None:
    mc = PryCrawlSync("http://localhost:8002")
    assert mc._client.base_url == "http://localhost:8002"


def test_prycrawlsync_init_with_key() -> None:
    mc = PryCrawlSync("http://localhost:8002", api_key="test-key")
    assert mc._client._headers["Authorization"] == "Bearer test-key"


def test_prycrawl_health_returns_dict() -> None:
    mc = PryCrawl("http://localhost:8002")
    # Just verify the method exists and returns a coroutine
    coro = mc.health()
    assert hasattr(coro, "__await__")
