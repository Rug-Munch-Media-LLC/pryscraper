"""Shared fixtures for the x402 gate tests.

The internal (first-party) free path keeps a process-wide seen-signature cache.
Tests that mint a credential in the same second as another test would therefore
look like a replay of it, so every test starts from an empty cache.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import pytest

from pry.payments.x402_middleware.internal import _SEEN_SIGNATURES

# Split scenario files rely on the shared router fixture (regression: settle_1/_2
# were split without it, so pytest reported "fixture 'router' not found").
from tests.x402._x402_facilitator_support import (  # noqa: F401
    _eip7702_ok,
    router,
)


@pytest.fixture(autouse=True)
def _clear_internal_replay_cache():
    """Start and finish each test with an empty internal replay cache."""
    _SEEN_SIGNATURES.clear()
    yield
    _SEEN_SIGNATURES.clear()
