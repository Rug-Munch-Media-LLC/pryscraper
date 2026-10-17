"""Tests for SSRF and path-traversal guard."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from pry.core.errors import InvalidRequestError
from pry.engine import url_guard
from pry.engine.url_guard import safe_get, validate_redirect_url, validate_url


class TestValidateURL:
    def test_accepts_normal_https(self):
        result = validate_url("https://example.com/page")
        assert result == "https://example.com/page"

    def test_accepts_normal_http(self):
        result = validate_url("http://example.com/page")
        assert result == "http://example.com/page"

    def test_accepts_https_with_path_and_query(self, monkeypatch):
        # DNS is validated at import; stub it so the test does not depend on
        # an external resolver (the guard now fails closed on DNS errors).
        monkeypatch.setattr(
            "pry.engine.url_guard.socket.getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
        )
        url = "https://api.example.com/v1/data?key=val&page=2#section"
        result = validate_url(url)
        assert result == url

    def test_rejects_empty_url(self):
        with pytest.raises(InvalidRequestError):
            validate_url("")

    def test_rejects_ftp_scheme(self):
        with pytest.raises(InvalidRequestError):
            validate_url("ftp://example.com/file")

    def test_rejects_file_scheme(self):
        with pytest.raises(InvalidRequestError):
            validate_url("file:///etc/passwd")

    def test_rejects_javascript_scheme(self):
        with pytest.raises(InvalidRequestError):
            validate_url("javascript:alert(1)")

    def test_rejects_localhost_hostname(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://localhost:8080/admin")

    def test_rejects_localhost_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://127.0.0.1:8080/admin")

    def test_rejects_private_ip_10_dot(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://10.0.0.1/admin")

    def test_rejects_private_ip_192_168(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://192.168.1.1/admin")

    def test_rejects_private_ip_172(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://172.16.0.1/admin")

    def test_rejects_internal_hostname(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://" + "internal" + ".corp" + "/admin")

    def test_rejects_kubernetes_metadata(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://kubernetes.default.svc.cluster.local")

    def test_rejects_embedded_credentials(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://user:pass@example.com/")

    def test_rejects_path_traversal_simple(self):
        with pytest.raises(InvalidRequestError):
            validate_url("https://example.com/../../etc/passwd")

    def test_rejects_path_traversal_encoded(self):
        with pytest.raises(InvalidRequestError):
            validate_url("https://example.com/%2e%2e%2fetc/passwd")

    def test_rejects_path_traversal_double_encoded(self):
        with pytest.raises(InvalidRequestError):
            validate_url("https://example.com/%252e%252e%252fetc")

    def test_rejects_tailscale_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://" + "100." + "64.0.1/")

    def test_rejects_empty_hostname(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http:///path")

    def test_rejects_docker_host(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://docker/container")

    def test_rejects_metadata_google(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://" + "metadata.google" + ".internal" + "/")

    def test_rejects_link_local_ipv6(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://[fe80::1]/")

    def test_rejects_loopback_ipv6(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://[::1]/")

    def test_rejects_ipv4_mapped_loopback_ipv6(self):
        """::ffff:127.0.0.1 is the IPv4-mapped loopback — an SSRF bypass
        vector that must be rejected like the plain loopback itself."""
        with pytest.raises(InvalidRequestError):
            validate_url("http://[::ffff:127.0.0.1]/")

    def test_rejects_ipv4_mapped_private_ipv6(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://[::ffff:10.0.0.1]/")

    def test_rejects_ipv4_mapped_metadata_ipv6(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://[::ffff:169.254.169.254]/latest/meta-data/")

    def test_accepts_public_ipv6_literal(self):
        result = validate_url("http://[2001:db8::1]/")
        assert result == "http://[2001:db8::1]/"

    def test_rejects_cloud_metadata_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://169.254.169.254/latest/meta-data/iam/security-credentials/")

    def test_rejects_zero_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_url("http://0.0.0.0/")

    def test_dns_resolution_blocks_private_ip_by_default(self, monkeypatch):
        """resolve_dns=True is the default: a public hostname that resolves to a
        private IP (DNS rebinding / metadata attack) must be rejected."""

        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(InvalidRequestError):
            validate_url("http://public.example.com/")

    def test_dns_resolution_blocks_metadata_ip_by_default(self, monkeypatch):
        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80)),
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(InvalidRequestError):
            validate_url("http://public.example.com/")

    def test_resolve_dns_false_skips_dns_check(self, monkeypatch):
        """resolve_dns=False remains available for callers that already vetted
        the address."""

        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        result = validate_url("http://public.example.com/", resolve_dns=False)
        assert result == "http://public.example.com/"


class TestValidateRedirectURL:
    def test_redirect_rejects_loopback(self):
        with pytest.raises(InvalidRequestError):
            validate_redirect_url("http://127.0.0.1/admin")

    def test_redirect_rejects_metadata_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_redirect_url("http://169.254.169.254/latest/meta-data/")

    def test_redirect_rejects_private_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_redirect_url("http://10.0.0.1/")

    def test_redirect_rejects_cgnat_ip(self):
        with pytest.raises(InvalidRequestError):
            validate_redirect_url("http://" + "100." + "64.0.1/")

    def test_redirect_rejects_loopback_ipv6(self):
        with pytest.raises(InvalidRequestError):
            validate_redirect_url("http://[::1]/")

    def test_redirect_accepts_public(self):
        result = validate_redirect_url("https://example.com/next")
        assert result == "https://example.com/next"


class TestSafeGet:
    def _redirect_response(self, status: int, location: str) -> httpx.Response:
        return httpx.Response(
            status,
            request=httpx.Request("GET", "https://example.com/start"),
            headers={"location": location},
        )

    def _ok_response(self, url: str = "https://example.com/start") -> httpx.Response:
        return httpx.Response(200, request=httpx.Request("GET", url), text="ok")

    @pytest.mark.asyncio
    async def test_blocks_redirect_to_loopback(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[self._redirect_response(302, "http://127.0.0.1/evil")])
        with pytest.raises(InvalidRequestError):
            await safe_get(client, "https://example.com/start")
        # The unsafe redirect must not be followed.
        assert client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_blocks_redirect_to_metadata_ip(self):
        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[self._redirect_response(302, "http://169.254.169.254/latest/meta-data/")]
        )
        with pytest.raises(InvalidRequestError):
            await safe_get(client, "https://example.com/start")
        assert client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_follows_safe_redirect(self):
        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=[
                self._redirect_response(302, "https://example.com/next"),
                self._ok_response("https://example.com/next"),
            ]
        )
        resp = await safe_get(client, "https://example.com/start")
        assert resp.status_code == 200
        assert client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_redirect_loop_hits_max_redirects(self):
        client = AsyncMock()
        client.get = AsyncMock(
            side_effect=lambda url, **kwargs: self._redirect_response(
                302, "https://example.com/loop"
            )
        )
        resp = await safe_get(client, "https://example.com/start", max_redirects=3)
        assert resp.status_code == 302
        assert client.get.await_count == 4  # initial + 3 redirect hops

    @pytest.mark.asyncio
    async def test_rejects_private_initial_url(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=self._ok_response())
        with pytest.raises(InvalidRequestError):
            await safe_get(client, "http://127.0.0.1/")
        assert client.get.await_count == 0
