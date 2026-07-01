"""Integration tests for MCP + x402 middleware in api.py."""

from __future__ import annotations

import base64
import json
import socket
import subprocess
import time

import httpx
from fastapi.testclient import TestClient

from api import app


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
            httpx.get(url, timeout=1.0)
            return
        except Exception:
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
    """

    def test_mcp_sse_session_roundtrip(self) -> None:
        port = _find_free_port()
        proc = subprocess.Popen(
            [
                "python3",
                "-m",
                "uvicorn",
                "api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd="/home/dev/pry",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(f"{base_url}/health")

            # The private query param closes the SSE stream after 1 message event
            # so the server doesn't keep the connection open after the test.
            with (
                httpx.Client(timeout=10.0) as client,
                client.stream("GET", f"{base_url}/mcp/sse?_sse_test_close_after=1") as sse_response,
            ):
                assert sse_response.status_code == 200
                assert sse_response.headers["content-type"].startswith("text/event-stream")

                buffer = ""
                event_count = 0
                for chunk in sse_response.iter_text():
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
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


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
        networks = {a["network"] for a in body["accepts"]}
        assert "base" in networks
        assert "solana" in networks

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
