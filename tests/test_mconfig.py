"""Tests for Pry config."""

from mconfig import PryConfig


def test_config_get_default() -> None:
    c = PryConfig()
    assert c.get("nonexistent.key", "fallback") == "fallback"


def test_config_get_retry_exists() -> None:
    c = PryConfig()
    val = c.get("retry.max_attempts")
    assert isinstance(val, int)
    assert val > 0


def test_config_get_rate_limit_exists() -> None:
    c = PryConfig()
    val = c.get("rate_limit.rpm")
    assert isinstance(val, int)
    assert val > 0


def test_config_to_dict_excludes_private() -> None:
    c = PryConfig()
    d = c.to_dict()
    assert "_proxy_chain" not in d
    assert "_proxy_url" not in d


def test_config_update_returns_ok() -> None:
    c = PryConfig()
    result = c.update({"retry": {"max_attempts": 5}})
    assert result["status"] == "ok"
    assert c.get("retry.max_attempts") == 5


def test_config_get_proxy_url_string_or_none() -> None:
    c = PryConfig()
    url = c.get_proxy_url()
    assert url is None or isinstance(url, str)
