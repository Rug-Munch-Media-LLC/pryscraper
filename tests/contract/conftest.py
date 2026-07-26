"""Pact contract test configuration for pryscraper consumer tests."""

import os

import pytest


@pytest.fixture(scope="session")
def pact_broker_url():
    return os.environ.get("PACT_BROKER_URL", "http://localhost:9292")


@pytest.fixture(scope="session")
def pact_broker_token():
    return os.environ.get("PACT_BROKER_TOKEN", "pact_user:pact_password")
