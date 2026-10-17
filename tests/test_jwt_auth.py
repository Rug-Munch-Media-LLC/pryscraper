"""Tests for jwt_auth.py — JWT token validation & API key auth."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from pry.core.jwt_auth import (
    _fetch_public_key,
    _load_key,
    is_jwt,
    validate_rmi_jwt,
)

# ── _load_key ──


def test_load_key_from_env(tmp_path):
    """Key that is a file path loads the file content."""
    key_file = tmp_path / "key.pem"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nABCD\n-----END RSA PRIVATE KEY-----")
    result = _load_key(str(key_file))
    assert "BEGIN RSA" in result


def test_load_key_inline():
    """Key that is inline PEM returns as-is."""
    result = _load_key("inline-pem-data")
    assert result == "inline-pem-data"


# ── _fetch_public_key ──


def test_fetch_public_key_from_cache():
    """Cached key within TTL returns cached value."""
    with patch("pry.core.jwt_auth._jwks_cache", {"key": "cached-key", "fetched_at": time.time()}):
        assert _fetch_public_key() == "cached-key"


def test_fetch_public_key_from_env():
    """Env var PUBLIC_KEY is loaded when cache is stale."""
    with (
        patch("pry.core.jwt_auth._jwks_cache", {"key": None, "fetched_at": 0.0}),
        patch("pry.core.jwt_auth._JWT_PUBLIC_KEY", "/path/to/key.pem"),
        patch("pry.core.jwt_auth._load_key", return_value="env-key"),
    ):
        result = _fetch_public_key()
        assert result == "env-key"


def test_fetch_public_key_no_env_no_jwks():
    """No env key and JWKS unreachable returns None."""
    with (
        patch("pry.core.jwt_auth._jwks_cache", {"key": None, "fetched_at": 0.0}),
        patch("pry.core.jwt_auth._JWT_PUBLIC_KEY", ""),
        patch("pry.core.jwt_auth._JWKS_URL", "https://invalid.example.com/jwks"),
    ):
        result = _fetch_public_key()
        assert result is None


def test_fetch_public_key_invalid_scheme():
    """JWKS URL with non-http scheme returns None."""
    with (
        patch("pry.core.jwt_auth._jwks_cache", {"key": None, "fetched_at": 0.0}),
        patch("pry.core.jwt_auth._JWT_PUBLIC_KEY", ""),
        patch("pry.core.jwt_auth._JWKS_URL", "file:///etc/passwd"),
    ):
        result = _fetch_public_key()
        assert result is None


@patch("pry.core.jwt_auth.urllib.request.urlopen")
def test_fetch_public_key_jwks_success(mock_urlopen):
    """JWKS endpoint returning PEM works."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"pem": "jwks-pem"}).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    with (
        patch("pry.core.jwt_auth._jwks_cache", {"key": None, "fetched_at": 0.0}),
        patch("pry.core.jwt_auth._JWT_PUBLIC_KEY", ""),
        patch("pry.core.jwt_auth._JWKS_URL", "https://example.com/jwks"),
    ):
        result = _fetch_public_key()
        assert result == "jwks-pem"


@patch("pry.core.jwt_auth.urllib.request.urlopen")
def test_fetch_public_key_jwks_no_pem(mock_urlopen):
    """JWKS endpoint without PEM field returns None."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"keys": []}).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    with (
        patch("pry.core.jwt_auth._jwks_cache", {"key": None, "fetched_at": 0.0}),
        patch("pry.core.jwt_auth._JWT_PUBLIC_KEY", ""),
        patch("pry.core.jwt_auth._JWKS_URL", "https://example.com/jwks"),
    ):
        result = _fetch_public_key()
        assert result is None


# ── validate_rmi_jwt ──


def test_validate_rmi_jwt_no_jwt_library():
    """Without pyjwt library, returns None."""
    with patch("pry.core.jwt_auth._HAS_JWT", False):
        assert validate_rmi_jwt("some.token.here") is None


def test_validate_rmi_jwt_empty_token():
    """Empty token returns None."""
    assert validate_rmi_jwt("") is None


def test_validate_rmi_jwt_no_key():
    """No key configured returns None."""
    with (
        patch("pry.core.jwt_auth._HAS_JWT", True),
        patch("pry.core.jwt_auth._fetch_public_key", return_value=None),
    ):
        assert validate_rmi_jwt("some.token.here") is None


@patch("pry.core.jwt_auth.pyjwt.decode")
def test_validate_rmi_jwt_success(mock_decode):
    """Valid JWT returns claims dict."""
    mock_decode.return_value = {
        "sub": "user_123",
        "email": "a@b.com",
        "tier": "PRO",
        "role": "ADMIN",
        "wallet": "0xabc",
    }
    with (
        patch("pry.core.jwt_auth._HAS_JWT", True),
        patch("pry.core.jwt_auth._fetch_public_key", return_value="pub-key"),
    ):
        claims = validate_rmi_jwt("valid.jwt.token")
        assert claims is not None
        assert claims["id"] == "user_123"
        assert claims["tier"] == "PRO"
        assert claims["wallet"] == "0xabc"


@patch("pry.core.jwt_auth.pyjwt.decode")
def test_validate_rmi_jwt_failure(mock_decode):
    """Invalid JWT returns None."""
    mock_decode.side_effect = ValueError("bad token")
    with (
        patch("pry.core.jwt_auth._HAS_JWT", True),
        patch("pry.core.jwt_auth._fetch_public_key", return_value="pub-key"),
    ):
        assert validate_rmi_jwt("bad.jwt.token") is None


# ── SECURITY: algorithm-confusion + expiry enforcement (2026-08-20 audit) ──


def test_validate_rmi_jwt_rejects_non_rs256_algorithm():
    """A configured non-RS256 algorithm (e.g. HS256) must be refused.

    Regression: the old code fell back to HS256 using the RSA *public* key
    as the HMAC secret — anyone with the public key could forge tokens.
    """
    with (
        patch("pry.core.jwt_auth._HAS_JWT", True),
        patch("pry.core.jwt_auth._JWT_ALGORITHM", "HS256"),
        patch("pry.core.jwt_auth._fetch_public_key", return_value="pub-key"),
        patch("pry.core.jwt_auth.pyjwt.decode") as mock_decode,
    ):
        assert validate_rmi_jwt("some.jwt.token") is None
        mock_decode.assert_not_called()


@patch("pry.core.jwt_auth.pyjwt.decode")
def test_validate_rmi_jwt_enforces_rs256_and_exp(mock_decode):
    """RS256 tokens are decoded with exp required."""
    mock_decode.return_value = {"sub": "u", "exp": time.time() + 60}
    with (
        patch("pry.core.jwt_auth._HAS_JWT", True),
        patch("pry.core.jwt_auth._JWT_ALGORITHM", "RS256"),
        patch("pry.core.jwt_auth._fetch_public_key", return_value="pub-key"),
    ):
        validate_rmi_jwt("good.jwt.token")
        _args, kwargs = mock_decode.call_args
        expected = ["RS256"]
        assert kwargs.get("algorithms") == expected
        expected_2 = ["exp"]
        assert kwargs.get("options", {}).get("require") == expected_2


# ── is_jwt ──


def test_is_jwt_valid():
    """Standard 3-part JWT returns True."""
    assert is_jwt("header.payload.signature") is True


def test_is_jwt_two_parts():
    """2-part token (API key) returns False."""
    assert is_jwt("pry_abc123") is False


def test_is_jwt_empty():
    """Empty token returns False."""
    assert is_jwt("") is False


def test_is_jwt_one_part():
    """Single-part token returns False."""
    assert is_jwt("justonepart") is False


def test_is_jwt_empty_parts():
    """Token with empty parts returns False."""
    assert is_jwt("header..sig") is False
