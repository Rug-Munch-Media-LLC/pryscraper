"""Shared fixtures for the x402 gate tests.

The internal (first-party) free path keeps a process-wide seen-signature cache.
Tests that mint a credential in the same second as another test would therefore
look like a replay of it, so every test starts from an empty cache.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import pytest

from pry.payments.x402_middleware.internal import _SEEN_SIGNATURES


@pytest.fixture(autouse=True)
def _clear_internal_replay_cache():
    """Start and finish each test with an empty internal replay cache."""
    _SEEN_SIGNATURES.clear()
    yield
    _SEEN_SIGNATURES.clear()
