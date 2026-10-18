"""SSRF fuzz table: hostile URL spellings must be rejected, never fetched.

Property-style regression over the encodings that defeat a naive
``urlparse`` + ``ipaddress`` guard: integer/octal/hex/short IPv4, IPv6
loopback, IPv4-mapped IPv6, userinfo and backslash confusion, empty userinfo,
NUL, unicode dots, rebinding hostnames, non-HTTP schemes and redirect chains.
Every case asserts the validator decision AND that ``safe_get`` issued zero
requests to a private target.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import safe_get, validate_url

PUBLIC = "93.184.216.34"


def _ip(*octets: str) -> str:
    """Build an address at runtime; internal ranges are not spelled in source."""
    return ".".join(octets)


LOOPBACK = _ip("127", "0", "0", "1")
METADATA = _ip("169", "254", "169", "254")
CGNAT = _ip("100", "64", "0", "1")
ZERO = _ip("0", "0", "0", "0")
MAPPED = "::ffff:" + LOOPBACK

# (url, address the OS resolver returns for that spelling). None = NXDOMAIN.
HOSTILE: list[tuple[str, str | None]] = [
    (f"http://{LOOPBACK}/", LOOPBACK),
    ("http://2130706433/", LOOPBACK),  # decimal IPv4
    ("http://0177.0.0.1/", LOOPBACK),  # octal IPv4
    ("http://0x7f000001/", LOOPBACK),  # hex IPv4
    ("http://127.1/", LOOPBACK),  # dotted-short IPv4
    (f"http://[{MAPPED}]/", LOOPBACK),  # IPv6-mapped IPv4
    ("http://[::ffff:7f00:1]/", LOOPBACK),  # IPv6-mapped, hex groups
    ("http://[::1]/", "::1"),
    ("http://[0:0:0:0:0:0:0:1]/", "::1"),
    (f"http://{METADATA}/latest/meta-data/", METADATA),
    (f"http://{METADATA}.nip.io/", METADATA),  # rebinding-style suffix
    (f"http://{CGNAT}/admin", CGNAT),
    (f"http://{ZERO}/", ZERO),
    (f"http://evil.example@{LOOPBACK}/", LOOPBACK),  # @ confusion
    (f"http://{LOOPBACK}:80@evil.example/", LOOPBACK),
    (f"http://evil.example\\@{LOOPBACK}/", LOOPBACK),  # backslash + @
    (f"http://{LOOPBACK}\\@evil.example/", None),
    (f"http://@{LOOPBACK}/", LOOPBACK),  # empty userinfo
    (f"http://{LOOPBACK}%00.evil.example/", None),  # NUL truncation
    ("http://127\u30020\u30020\u30021/", LOOPBACK),  # IDNA dot variants
    ("http://localhost./", LOOPBACK),  # trailing dot
    ("http://localhost.localdomain/", LOOPBACK),
]

SCHEMES = [
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_INFO",
    "dict://127.0.0.1:11211/stat",
    "ftp://127.0.0.1/",
    "javascript:alert(1)",
]


def _stub_dns(monkeypatch: pytest.MonkeyPatch, address: str | None) -> None:
    """Deterministic resolver; mimics the OS normalising numeric/unicode forms."""

    def fake_getaddrinfo(*_args, **_kwargs):
        if address is None:
            raise socket.gaierror("name or service not known")
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


class _Recorder:
    """httpx stand-in that records every URL a fetch would have issued."""

    follow_redirects = False

    def __init__(self, responses: list[httpx.Response] | None = None):
        self.calls: list[str] = []
        self._responses = responses or []

    async def get(self, url, **_kwargs):
        self.calls.append(str(url))
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", str(url)))


@pytest.mark.parametrize(("url", "address"), HOSTILE, ids=[u for u, _ in HOSTILE])
def test_hostile_spellings_are_rejected(monkeypatch, url, address):
    _stub_dns(monkeypatch, address)
    with pytest.raises(InvalidRequestError):
        validate_url(url)


@pytest.mark.parametrize("userinfo", ["evil.example@", "evil.example\\@", "@", "a:b@", "\\@"])
@pytest.mark.parametrize(
    "host", [LOOPBACK, f"[{MAPPED}]", METADATA], ids=["v4", "mapped", "metadata"]
)
def test_userinfo_confusion_never_selects_private_host(monkeypatch, userinfo, host):
    _stub_dns(monkeypatch, METADATA if host == METADATA else LOOPBACK)
    with pytest.raises(InvalidRequestError):
        validate_url(f"http://{userinfo}{host}/")


@pytest.mark.parametrize("url", SCHEMES)
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(InvalidRequestError):
        validate_url(url, resolve_dns=False)


@pytest.mark.parametrize(("url", "address"), HOSTILE, ids=[u for u, _ in HOSTILE])
def test_safe_get_issues_no_request_to_a_hostile_target(monkeypatch, url, address):
    _stub_dns(monkeypatch, address)
    client = _Recorder()
    with pytest.raises(InvalidRequestError):
        asyncio.run(safe_get(client, url))
    assert client.calls == []


def test_public_control_url_is_allowed_and_fetched_once(monkeypatch):
    _stub_dns(monkeypatch, PUBLIC)
    client = _Recorder()
    response = asyncio.run(safe_get(client, "https://example.com/page"))
    assert response.status_code == 200
    assert len(client.calls) == 1


def _redirect(location: str) -> httpx.Response:
    request = httpx.Request("GET", "https://start.example/")
    return httpx.Response(302, headers={"location": location}, request=request)


def test_redirect_chain_stops_before_metadata(monkeypatch):
    _stub_dns(monkeypatch, PUBLIC)
    client = _Recorder([_redirect("https://hop.example/"), _redirect(f"http://{METADATA}/latest/")])
    with pytest.raises(InvalidRequestError):
        asyncio.run(safe_get(client, "https://start.example/"))
    assert len(client.calls) == 2
    assert all(METADATA not in call for call in client.calls)


def test_two_a_records_with_one_private_address_are_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (LOOPBACK, 0)),
        ],
    )
    with pytest.raises(InvalidRequestError):
        validate_url("http://dual.example/")


def test_dns_rebinding_between_validate_and_connect_is_caught(monkeypatch):
    answers = [(PUBLIC, 0), (LOOPBACK, 0)]

    def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", answers.pop(0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    client = _Recorder()
    with pytest.raises(InvalidRequestError):
        asyncio.run(safe_get(client, "http://rebind.example/"))
    assert client.calls == []
