# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pact consumer tests: pryscraper expects specific behavior from rmi-backend API.

These tests define the contract that rmi-backend (provider) must satisfy.
If rmi-backend changes its API in a way that breaks pryscraper, the Pact
verification will fail — catching the breakage BEFORE deployment.

Uses the pact-python v3 API (``pact.v3.Pact``), which is the supported API in
pact-python 2.x and beyond. The legacy ``pact.Consumer`` / ``pact.Provider`` /
``pact.Like`` API is deprecated (removal planned for Pact Python v3, see
pact-foundation/pact-python#396) — do not migrate back.

NOTE on design: the v3 mock server verifies ALL registered interactions in a
single serve session (``server.matched`` is only true when every interaction
was exercised). The whole contract is therefore registered up front and all
endpoints are exercised in one ``with pact_instance.serve(...)`` block. A
per-endpoint serve would report mismatches for the other registered
interactions.

Run (explicit contract job only — excluded from the default suite via
``--ignore=tests/contract`` in pyproject addopts):
    python -m pytest tests/contract/ -v --tb=short
Publish: pact-broker publish tests/contract/pacts/ \\
             --consumer-app-version $(git rev-parse --short HEAD) \\
             --branch $(git rev-parse --abbrev-ref HEAD) \\
             --broker-base-url $PACT_BROKER_URL
"""

import os

import pytest

# Skip cleanly when pact-python is not installed (e.g. minimal dev envs).
# The CI contract job installs the `pact-python` dev extra explicitly.
#
# pact-python 3.x: the API that lived in `pact.v3` (2.x) is now the default
# `pact` package (the module layout below the top level changed; the v3 API
# kept the same DSL — upon_receiving/given/with_request/will_respond_with).
pytest.importorskip("pact")
from pact import Pact, match

PACT_DIR = os.path.join(os.path.dirname(__file__), "pacts")

pact_instance = Pact("pryscraper", "rmi-backend")


def _register_interactions() -> None:
    """Register the full pryscraper ↔ rmi-backend contract."""
    # 1. Health check
    (
        pact_instance.upon_receiving("a health check request")
        .given("rmi-backend is running")
        .with_request("GET", "/health")
        .will_respond_with(200)
        .with_body(
            {
                "status": match.like("healthy"),
                "version": match.like("0.1.0"),
            }
        )
    )

    # 2. Token scan
    (
        pact_instance.upon_receiving("a token scan request")
        .given("a token exists for scanning")
        .with_request("GET", "/api/v1/token/0x1234567890abcdef")
        .with_query_parameter("chain", "eth")
        .will_respond_with(200)
        .with_body(
            {
                "token_address": match.like("0x1234567890abcdef"),
                "chain": match.like("eth"),
                "risk_score": match.like(75),
                "findings": match.like([]),
            }
        )
    )

    # 3. Error handling for invalid tokens
    (
        pact_instance.upon_receiving("a request for non-existent token")
        .given("an invalid token address")
        .with_request("GET", "/api/v1/token/0xdeadbeef")
        .will_respond_with(404)
        .with_body(
            {
                "error": match.like("not_found"),
                "message": match.like("Token not found"),
            }
        )
    )


def test_rmi_backend_contract() -> None:
    """The mock serves every registered interaction; the consumer matches it.

    Exercises the full contract in one serve session so the v3 mock server
    can verify every interaction was called (server.matched).
    """
    _register_interactions()

    with pact_instance.serve(port=0) as server:
        import requests

        # Health check
        health = requests.get(f"{server.url}/health", timeout=10)
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "healthy"
        assert isinstance(body["version"], str)

        # Token scan
        scan = requests.get(
            f"{server.url}/api/v1/token/0x1234567890abcdef",
            params={"chain": "eth"},
            timeout=10,
        )
        assert scan.status_code == 200
        data = scan.json()
        assert data["token_address"] == "0x1234567890abcdef"
        assert data["chain"] == "eth"
        assert isinstance(data["risk_score"], int)
        assert isinstance(data["findings"], list)

        # Error handling
        missing = requests.get(f"{server.url}/api/v1/token/0xdeadbeef", timeout=10)
        assert missing.status_code == 404
        err = missing.json()
        assert err["error"] == "not_found"
        assert isinstance(err["message"], str)

        # Every registered interaction must have been exercised with no
        # mismatches, or the consumer/provider contract is broken.
        assert server.matched, f"pact mismatches: {server.mismatches}"

    # Write the consumer contract artifact for provider verification /
    # pact-broker publishing.
    pact_instance.write_file(directory=PACT_DIR, overwrite=True)
