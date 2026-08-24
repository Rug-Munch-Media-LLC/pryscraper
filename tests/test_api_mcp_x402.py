# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Integration tests for MCP + x402 middleware in api.py."""

from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from pry.api.api import app

REPO_ROOT = Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_server(url: str, timeout: float = 30.0) -> None:
    """Poll url until it responds or timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=5.0)
            return
        except httpx.RequestError:
            time.sleep(0.5)
    raise TimeoutError(f"Server at {url} did not start within {timeout}s")


class TestMCPJsonRPC:
    """MCP JSON-RPC endpoint mounted at /mcp."""

    def test_mcp_initialize(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert data["result"]["serverInfo"]["name"] == "pry"
        caps = data["result"]["capabilities"]
        assert caps["resources"]["subscribe"] is True
        assert caps["logging"] == {}

    def test_mcp_tools_list(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert "tools" in result
        assert len(result["tools"]) >= 10
        names = {t["name"] for t in result["tools"]}
        assert "pry_scrape" in names
        assert "pry_x402_pricing" in names

    def test_mcp_prompts_get(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "prompts/get",
                "params": {
                    "name": "research_company",
                    "arguments": {"company_name": "Anthropic", "website": "https://anthropic.com"},
                },
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert "messages" in result
        assert len(result["messages"]) > 0
        assert "Anthropic" in result["messages"][0]["content"]["text"]

    def test_mcp_resources_list(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert len(result["resources"]) >= 3
        uris = {r["uri"] for r in result["resources"]}
        assert "pry://catalog" in uris
        assert "pry://x402/pricing" in uris

    def test_mcp_resource_subscribe_unsubscribe(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/subscribe",
                "params": {"uri": "pry://stats"},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["subscribed"] is True

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/unsubscribe",
                "params": {"uri": "pry://stats"},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["unsubscribed"] is True

    def test_mcp_logging_set_level(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "logging/setLevel",
                "params": {"level": "debug"},
            },
        )
        assert response.status_code == 200
        assert response.json()["result"] == {}

    def test_mcp_completion(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 8,
                "method": "completion/complete",
                "params": {
                    "ref": {"type": "ref/prompt", "name": "extract_contacts"},
                    "argument": {"name": "max_pages", "value": ""},
                },
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert "values" in result
        assert "20" in result["values"]

    def test_mcp_health(self) -> None:
        client = TestClient(app)
        response = client.get("/mcp/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["tools_count"] >= 10


class TestMCPSSE:
    """MCP HTTP+SSE transport.

    httpx's ASGITransport cannot consume an infinite streaming response, so
    these tests start a real uvicorn process and connect over HTTP.

    Determinism notes (the test was flaky under parallel load):
      * the port chosen by ``_find_free_port`` can be stolen by another
        process between the probe and uvicorn's bind — the spawn helper
        detects an early process exit and retries on a fresh port;
      * a slow scheduler can push an SSE read past httpx's read timeout —
        the per-read timeout is raised and a wall-clock deadline bounds the
        whole roundtrip with a clear failure message;
      * the subprocess is always reaped (terminate -> wait -> kill).
    """

    @staticmethod
    def _spawn_server(max_attempts: int = 3) -> tuple[subprocess.Popen, str, int]:
        """Start uvicorn on a free port; retry when the port is stolen.

        Returns ``(proc, base_url, port)``. The caller must terminate the
        process in a ``finally`` block.
        """
        python_bin = shutil.which("python3") or "python3"
        last_poll: int | None = None
        for _ in range(max_attempts):
            port = _find_free_port()
            proc = subprocess.Popen(  # noqa: S603 - argv is static; port comes from trusted _find_free_port()
                [
                    python_bin,
                    "-m",
                    "uvicorn",
                    "pry.api.api:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                shell=False,
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                base_url = f"http://127.0.0.1:{port}"
                _wait_for_server(f"{base_url}/health", timeout=45.0)
                return proc, base_url, port
            except TimeoutError:
                # The port was likely stolen before uvicorn bound it: the
                # process exits immediately. Reap it and retry on a new port.
                last_poll = proc.poll()
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if last_poll is not None:
                    continue
                raise
        raise TimeoutError(
            f"Server did not start after {max_attempts} attempts "
            f"(last process exit code: {last_poll})"
        )

    @staticmethod
    def _terminate_server(proc: subprocess.Popen) -> None:
        """Reap the uvicorn subprocess (terminate -> wait -> kill)."""
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def test_mcp_sse_session_roundtrip(self) -> None:
        proc, base_url, _ = self._spawn_server()
        try:
            # The private query param closes the SSE stream after 1 message event
            # so the server doesn't keep the connection open after the test.
            deadline = time.monotonic() + 30.0
            with (
                httpx.Client(timeout=30.0) as client,
                client.stream("GET", f"{base_url}/mcp/sse?_sse_test_close_after=1") as sse_response,
            ):
                assert sse_response.status_code == 200
                assert sse_response.headers["content-type"].startswith("text/event-stream")

                buffer = ""
                event_count = 0
                for chunk in sse_response.iter_text():
                    if time.monotonic() > deadline:
                        raise AssertionError(
                            f"SSE roundtrip exceeded 30s deadline; received {event_count} events"
                        )
                    buffer += chunk
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        event_count += 1
                        if event_count == 1:
                            assert "event: endpoint" in event
                            post_url = event.split("data: ", 1)[1]
                            init_msg = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "initialize",
                                "params": {},
                            }
                            post_resp = client.post(post_url, json=init_msg)
                            assert post_resp.status_code == 202
                        elif event_count == 2:
                            assert "event: message" in event
                            data_line = event.split("data: ", 1)[1]
                            response = json.loads(data_line)
                            assert response["result"]["protocolVersion"] == "2024-11-05"
                            return
                raise AssertionError("SSE stream closed before response event")
        finally:
            self._terminate_server(proc)


class TestX402Middleware:
    """x402 payment gating on paid endpoints."""

    def test_paid_endpoint_requires_payment(self) -> None:
        client = TestClient(app)
        response = client.post("/v1/scrape", json={"url": "https://example.com"})
        assert response.status_code == 402
        body = response.json()
        assert body["x402Version"] == 1
        assert "accepts" in body
        assert "PAYMENT-REQUIRED" in response.headers
        # The challenge exposes the canonical CAIP-2 acceptance surface
        # (multi-asset mode): every supported network appears in accepts.
        networks = {a["network"] for a in body["accepts"]}
        assert "eip155:8453" in networks  # Base
        assert "solana:mainnet" in networks
        assert "tron:mainnet" in networks
        # Multi-asset acceptance: Solana USDT / TRON USDT / Arbitrum ARB are
        # quotable options with USD-equivalent atomic amounts.
        by_net_asset = {(a["network"], a["asset"]) for a in body["accepts"]}
        assert ("solana:mainnet", "USDT") in by_net_asset
        assert ("tron:mainnet", "USDT") in by_net_asset
        assert ("eip155:42161", "ARB") in by_net_asset
        # The challenge body also carries the supported surface tables.
        assert "networks" in body
        assert "supported_assets" in body

    def test_paid_endpoint_with_invalid_payment_still_402(self) -> None:
        client = TestClient(app)
        bad_sig = base64.b64encode(
            json.dumps({"payment_id": "x", "tx_hash": "y"}).encode()
        ).decode()
        response = client.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
            headers={"PAYMENT-SIGNATURE": bad_sig},
        )
        assert response.status_code == 402

    def test_x402_pricing_is_public(self) -> None:
        client = TestClient(app)
        response = client.get("/v1/x402/pricing")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "supported_networks" in data["data"]
        assert "solana" in data["data"]["supported_networks"]
        # Canonical CAIP-2 acceptance surface is exposed too.
        assert "networks" in data["data"]
        assert "caip2_networks" in data["data"]
        assert "asset_table" in data["data"]
        assert "verification_status" in data["data"]
        assert "eip155:8453" in data["data"]["caip2_networks"]
        assert "solana:mainnet" in data["data"]["caip2_networks"]
        assert "tron:mainnet" in data["data"]["caip2_networks"]
        assert data["data"]["asset_table"]["solana:mainnet"]["USDC"]["contract"] == (
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )

    def test_paid_endpoint_solana_tron_challenge_structure(self) -> None:
        """The 402 challenge for Solana/TRON carries valid header structure.

        The challenge (PAYMENT-REQUIRED header) must round-trip and the
        Solana/TRON acceptance options must carry the required x402 fields so
        an agent knows exactly how to pay. This only validates the challenge
        — on-chain settlement for those chains is a scaffolded [REVIEW] path.
        """
        client = TestClient(app)
        response = client.post("/v1/scrape", json={"url": "https://example.com"})
        assert response.status_code == 402
        header = response.headers["PAYMENT-REQUIRED"]
        decoded = json.loads(base64.b64decode(header).decode())
        assert decoded["x402Version"] == 1
        accepts = {f"{a['network']}:{a['asset']}": a for a in decoded["accepts"]}
        for key in ("solana:mainnet:USDC", "tron:mainnet:USDT"):
            assert key in accepts
            option = accepts[key]
            for field in (
                "scheme",
                "network",
                "maxAmountRequired",
                "resource",
                "payToAddress",
                "asset",
            ):
                assert field in option
            assert option["extra"]["caip2"] == option["network"]
            assert option["extra"]["verification"] in ("spl", "trc20")


class TestX402BatchPayments:
    """x402 batch payment flow."""

    def test_batch_payment_created(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/v1/x402/batch-payment",
            json={"operations": ["scrape", "crawl", "extract"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "batch_id" in data["data"]
        assert data["data"]["total_usd"] > 0
        assert len(data["data"]["operations"]) == 3
        assert "payment_required" in data["data"]
        assert "accepts" in data["data"]["payment_required"]

    def test_batch_payment_invalid_operations(self) -> None:
        client = TestClient(app)
        response = client.post(
            "/v1/x402/batch-payment",
            json={"operations": ["not_real"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is False
