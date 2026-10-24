# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fuzz tests for url_guard — SSRF/path-traversal guard invariants.

The guard is a security boundary: it must never crash on attacker-controlled
input, and it must be total — for ANY string it either rejects the URL with
InvalidRequestError (the documented error type) or returns the URL unchanged.

Invariants checked here:
    * validate_url(url, resolve_dns=False) never raises anything except
      InvalidRequestError (real DNS resolution is disabled so the property
      test is hermetic and fast).
    * A URL that passes validation is returned byte-for-byte unchanged.
    * validate_redirect_url(url) has the same totality property when DNS
      resolution is neutralized (monkeypatched to fail closed).
"""

import string
from unittest import mock
from urllib.parse import urlparse

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from pry.core.errors import InvalidRequestError
from pry.engine import url_guard
from pry.engine.url_guard import validate_redirect_url, validate_url

# Valid hostname alphabet (RFC 1123-ish: letters, digits, hyphen, dot, plus
# a few extra chars urlparse tolerates) for structured URL generation.
_HOST_ALPHABET = string.ascii_letters + string.digits + "-._~"

# A private/reserved net used to force rejection without DNS.
_PRIVATE_NETS_SAMPLE = ["10.0.0.0/8", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16"]


def _is_known_stdlib_parse_error(e: BaseException) -> bool:
    """Defensive guard for any residual stdlib parse leak.

    url_guard.py now wraps malformed-host parsing in InvalidRequestError, so
    this should never match; kept as a safety net so a future regression in
    urllib.parse behavior still fails the property test loudly instead of
    silently passing.
    """
    return isinstance(e, ValueError) and "Invalid IPv6 URL" in str(e)


def _assert_accepted_unchanged(url: str, result: str) -> None:
    """validate_url is documented to return the URL unchanged when accepted."""
    assert result == url, f"validate_url mutated accepted URL: {url!r} -> {result!r}"


@pytest.mark.parametrize("url", ["http://[", "http://[::1", "http://[::1]x"])
def test_unclosed_ipv6_bracket_raises_invalid_request_error(url: str) -> None:
    """An unclosed '[' host must raise InvalidRequestError, not leak stdlib ValueError."""
    with pytest.raises(InvalidRequestError):
        validate_url(url, resolve_dns=False)


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(url=st.text(max_size=2048))
def test_validate_url_never_crashes_on_any_string(url: str) -> None:
    """Any string must be accepted or rejected with InvalidRequestError."""
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        if _is_known_stdlib_parse_error(e):
            return
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    scheme=st.sampled_from(["http", "https"]),
    host=st.text(alphabet=_HOST_ALPHABET, min_size=1, max_size=200),
    port=st.one_of(st.none(), st.integers(min_value=1, max_value=65535)),
    path=st.text(alphabet=string.printable, max_size=500),
    query=st.text(alphabet=string.printable, max_size=300),
    fragment=st.text(alphabet=string.printable, max_size=200),
)
def test_validate_url_well_formed_variants_never_crash(
    scheme: str, host: str, port: int | None, path: str, query: str, fragment: str
) -> None:
    """Structural URL variants (port, query, fragment, host) are total."""
    port_part = f":{port}" if port is not None else ""
    # Path is always separated by '/' — a well-formed URL cannot place a '['
    # directly in the authority (that is the stdlib-leak case, covered by the
    # any-string test + xfail regression above).
    url = f"{scheme}://{host}{port_part}/{path}"
    if query:
        url += f"?{query}"
    if fragment:
        url += f"#{fragment}"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)
    # Whatever passed must be a parseable URL with an http(s) scheme.
    parsed = urlparse(result)
    assert parsed.scheme in ("http", "https")


@settings(max_examples=300, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(url=st.text(max_size=2048))
def test_validate_redirect_url_never_crashes(url: str) -> None:
    """Redirect targets are attacker-controlled: rejection must be total.

    DNS resolution is neutralized (returns no addresses) so the property test
    never touches the network; the totality invariant still holds for the
    scheme / hostname / path checks.
    """
    # Patch by qualified name, not through the module attribute: url_guard no
        # longer imports socket at module scope, so `url_guard.socket` raised
        # AttributeError and this totality property silently stopped testing
        # anything. Patching "socket.getaddrinfo" works wherever the import lives.
        with mock.patch("socket.getaddrinfo", return_value=[]):
        try:
            result = validate_redirect_url(url)
        except InvalidRequestError:
            return
        except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
            if _is_known_stdlib_parse_error(e):
                return
            pytest.fail(f"validate_redirect_url crashed with {type(e).__name__} on {url!r}: {e}")
        _assert_accepted_unchanged(url, result)


@settings(max_examples=100, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    a=st.integers(min_value=0, max_value=255),
    b=st.integers(min_value=0, max_value=255),
    c=st.integers(min_value=0, max_value=255),
    d=st.integers(min_value=0, max_value=255),
)
def test_ipv4_literal_hosts_are_handled_totally(a: int, b: int, c: int, d: int) -> None:
    """Any IPv4 literal must either raise InvalidRequestError or pass unchanged."""
    url = f"http://{a}.{b}.{c}.{d}/"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)


@settings(max_examples=100, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    octet=st.integers(min_value=0, max_value=255),
    path=st.text(alphabet=_HOST_ALPHABET, max_size=300),
)
def test_private_ipv4_prefixes_always_rejected(octet: int, path: str) -> None:
    """A URL in any private net must be rejected, whatever the path looks like."""
    url = f"http://10.{octet}.0.1/{path}"
    try:
        validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    # 10.x.x.x is always RFC 1918 — reaching here means the guard missed it.
    pytest.fail(f"validate_url accepted private RFC 1918 URL: {url!r}")


# ── Scheme edge cases ────────────────────────────────────────────────────
# A scheme is attacker-controlled. Anything that is not http/https must be
# rejected; every scheme spelling (including case variants) must be handled
# without crashing, and accepted URLs must come back unchanged.
_SCHEME_ALPHABET = string.ascii_letters + string.digits + "+-."


@settings(max_examples=500, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    scheme=st.text(alphabet=_SCHEME_ALPHABET, min_size=0, max_size=32),
    host=st.text(alphabet=_HOST_ALPHABET, min_size=1, max_size=100),
)
def test_scheme_edge_cases_never_crash(scheme: str, host: str) -> None:
    """Any scheme spelling is accepted or rejected; never crashes, never mutates."""
    url = f"{scheme}://{host}/"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)
    # Only http/https may pass — case-insensitively.
    assert result.split("://", 1)[0].lower() in ("http", "https")


@pytest.mark.parametrize(
    "scheme",
    [
        "HTTP",
        "Https",
        "hTtP",
        "HTTPS",
        "ftp",
        "FTP",
        "file",
        "javascript",
        "gopher",
        "data",
        "ws",
        "wss",
        "mailto",
        "about",
        "blob",
        "chrome",
        "dict",
        "urn",
    ],
)
def test_scheme_case_and_non_http_variants(scheme: str) -> None:
    """Mixed-case http/https pass; every other scheme is rejected."""
    url = f"{scheme}://example.com/"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        assert scheme.lower() not in ("http", "https")
        return
    assert scheme.lower() in ("http", "https")
    assert result == url


def test_scheme_only_no_host_rejected() -> None:
    with pytest.raises(InvalidRequestError):
        validate_url("http://", resolve_dns=False)


def test_whitespace_scheme_rejected() -> None:
    with pytest.raises(InvalidRequestError):
        validate_url("http ://example.com", resolve_dns=False)


# ── Host edge cases ──────────────────────────────────────────────────────


@settings(max_examples=300, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    label=st.text(alphabet=_HOST_ALPHABET, min_size=1, max_size=60),
    path=st.text(alphabet=string.printable, max_size=200),
)
def test_host_label_edge_cases_never_crash(label: str, path: str) -> None:
    """Odd-but-parseable host labels (underscores, dots, tildes) are total."""
    url = f"http://{label}.example.com/{path}"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)


@settings(max_examples=200, deadline=2000, suppress_health_check=[HealthCheck.too_slow])
@given(
    host=st.text(alphabet=_HOST_ALPHABET + ":", min_size=1, max_size=120),
    path=st.text(alphabet=string.printable, max_size=200),
)
def test_ipv6_literal_hosts_never_crash(host: str, path: str) -> None:
    """IPv6-literal hosts (bracketed) are total — reject or pass unchanged."""
    url = f"http://[{host}]/{path}"
    try:
        result = validate_url(url, resolve_dns=False)
    except InvalidRequestError:
        return
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"validate_url crashed with {type(e).__name__} on {url!r}: {e}")
    _assert_accepted_unchanged(url, result)


@pytest.mark.parametrize(
    "host",
    [
        "[::ffff:127.0.0.1]",  # IPv4-mapped loopback — SSRF bypass vector
        "[::ffff:10.0.0.1]",  # IPv4-mapped RFC 1918
        "[::ffff:192.168.1.1]",  # IPv4-mapped RFC 1918
        "[::ffff:172.16.0.1]",  # IPv4-mapped RFC 1918
        "[::ffff:169.254.169.254]",  # IPv4-mapped cloud metadata
        "[::ffff:100.64.0.1]",  # IPv4-mapped CGNAT
        "[::ffff:0.0.0.0]",  # IPv4-mapped "this network"
        "[::1]",  # IPv6 loopback
        "[fe80::1]",  # IPv6 link-local
        "[fd00::1]",  # IPv6 ULA
        "[fc00::1]",  # IPv6 ULA
    ],
)
def test_ipv4_mapped_ipv6_private_hosts_rejected(host: str) -> None:
    """IPv4-mapped IPv6 literals must not bypass the private-IP guard."""
    url = f"http://{host}/"
    with pytest.raises(InvalidRequestError):
        validate_url(url, resolve_dns=False)


@pytest.mark.parametrize(
    "host",
    [
        "[2001:db8::1]",  # documentation range
        "[2606:4700:4700::1111]",  # public DNS
        "[2001:4860:4860::8888]",  # public DNS
    ],
)
def test_public_ipv6_literals_accepted(host: str) -> None:
    """Public IPv6 literals are legitimate targets and must pass."""
    url = f"http://{host}/"
    result = validate_url(url, resolve_dns=False)
    assert result == url


def test_ipv4_mapped_ipv6_metadata_rejected_via_dns_too(monkeypatch) -> None:
    """resolve_dns=True must also catch the mapped-metadata literal."""
    url = "http://[::ffff:169.254.169.254]/"
    with pytest.raises(InvalidRequestError):
        validate_url(url, resolve_dns=True)


@pytest.mark.parametrize(
    "host",
    ["example.com.", "my_host.example.com", "a.b.c.d.example.com", "xn--bcher-kva.example"],
)
def test_trailing_dot_and_underscore_hosts_accepted(host: str) -> None:
    """Trailing-dot / underscore / IDN-ish hosts are not internal resources."""
    url = f"http://{host}/"
    result = validate_url(url, resolve_dns=False)
    assert result == url
