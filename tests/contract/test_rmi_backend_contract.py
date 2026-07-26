"""Pact consumer tests: pryscraper expects specific behavior from rmi-backend API.

These tests define the contract that rmi-backend (provider) must satisfy.
If rmi-backend changes its API in a way that breaks pryscraper, the Pact
verification will fail — catching the breakage BEFORE deployment.

Run: python -m pytest tests/contract/ -v --tb=short
Publish: pact-broker publish tests/contract/pacts/ \\
             --consumer-app-version $(git rev-parse --short HEAD) \\
             --branch $(git rev-parse --abbrev-ref HEAD) \\
             --broker-base-url $PACT_BROKER_URL
"""

import atexit
import os

from pact import Consumer, Like, Provider

PACT_DIR = os.path.join(os.path.dirname(__file__), "pacts")

# Define the contract: pryscraper (consumer) expects rmi-backend (provider)
# to respond according to these interaction definitions.
pact = Consumer("pryscraper").has_pact_with(
    Provider("rmi-backend"),
    pact_dir=PACT_DIR,
    host_name="localhost",
    port=1234,
)

pact.start_service()
atexit.register(pact.stop_service)


def test_rmi_backend_health_check():
    """pryscraper expects rmi-backend to have a health endpoint."""
    expected = {
        "status": "healthy",
        "version": Like("0.1.0"),
    }

    (
        pact.given("rmi-backend is running")
        .upon_receiving("a health check request")
        .with_request("GET", "/health")
        .will_respond_with(200, body=expected)
    )

    with pact:
        import requests

        result = requests.get("http://localhost:1234/health")
        assert result.status_code == 200
        assert result.json()["status"] == "healthy"


def test_rmi_backend_token_scan():
    """pryscraper expects token scan endpoint to return structured data."""
    expected = {
        "token_address": Like("0x1234567890abcdef"),
        "chain": Like("eth"),
        "risk_score": Like(75),
        "findings": Like([]),
    }

    (
        pact.given("a token exists for scanning")
        .upon_receiving("a token scan request")
        .with_request("GET", "/api/v1/token/0x1234567890abcdef", query={"chain": "eth"})
        .will_respond_with(200, body=expected)
    )

    with pact:
        import requests

        result = requests.get(
            "http://localhost:1234/api/v1/token/0x1234567890abcdef", params={"chain": "eth"}
        )
        assert result.status_code == 200
        data = result.json()
        assert "risk_score" in data


def test_rmi_backend_error_handling():
    """pryscraper expects proper error responses for invalid tokens."""
    expected = {
        "error": Like("not_found"),
        "message": Like("Token not found"),
    }

    (
        pact.given("an invalid token address")
        .upon_receiving("a request for non-existent token")
        .with_request("GET", "/api/v1/token/0xdeadbeef")
        .will_respond_with(404, body=expected)
    )

    with pact:
        import requests

        result = requests.get("http://localhost:1234/api/v1/token/0xdeadbeef")
        assert result.status_code == 404
